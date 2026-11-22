import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.agent.run_manager import RunManager
from backend.app.core.config import Settings, get_settings
from backend.app.db.database import get_db_session
from backend.app.db.models import Run, Session as DBSession, ToolCall
from backend.app.sandbox.docker import DockerSandbox
from backend.app.sandbox.local import LocalSandbox

from backend.app.providers.factory import get_provider

router = APIRouter(prefix="/runs", tags=["runs"])

_run_manager = None


def get_run_manager(settings: Settings = Depends(get_settings)) -> RunManager:
    """Retrieve or instantiate the application's singleton RunManager.

    Injects current runtime settings, dynamic sandbox factory (Docker vs Local),
    and default model provider.
    """
    global _run_manager
    provider = get_provider(settings=settings)

    def sandbox_factory(workspace_root, slug):
        if settings.sandbox_backend == "docker":
            return DockerSandbox(
                workspace_root,
                slug,
                image=settings.default_sandbox_image,
                docker_host=settings.docker_socket_proxy,
                container_prefix=settings.sandbox_container_prefix,
            )
        return LocalSandbox(workspace_root)

    if _run_manager is None:
        _run_manager = RunManager(provider=provider, sandbox_factory=sandbox_factory)
    else:
        # Model/provider selection can change while the process is running.
        # New runs must use the current default instead of the provider cached
        # when this singleton was first created.
        _run_manager.provider = provider
        _run_manager.sandbox_factory = sandbox_factory
    return _run_manager


DEFAULT_MODEL = "qwen2.5-coder:latest"


def resolve_model(name: str | None, provider: str | None, settings: Settings) -> str:
    """Use the operator's selected model when no explicit one is given."""
    if name and name != DEFAULT_MODEL:
        return name
    target = (provider or settings.default_provider).lower()
    if target == "ollama" and settings.ollama_model:
        return settings.ollama_model
    if target == "llama_cpp" and settings.llamacpp_model:
        return settings.llamacpp_model
    from backend.app.core.provider_catalog import get_provider_entry
    entry = get_provider_entry(target)
    if entry and entry.get("kind") == "cloud":
        profile = settings.provider_profile(target)
        if profile.get("model"):
            return profile["model"]
        if entry.get("default_model"):
            return entry["default_model"]
    return name or DEFAULT_MODEL


class StartRunRequest(BaseModel):
    session_id: str
    prompt: str = Field(description="User prompt / instruction")
    model: str = Field(default=DEFAULT_MODEL)
    provider: str | None = Field(default=None, description="Optional provider override ('llama_cpp' or 'ollama')")
    policy_mode: str = Field(default="auto_edit", description="ask_all | auto_edit | full_auto")
    max_steps: int | None = Field(default=None, description="Override the configured max steps for this run")


class ApprovalActionItem(BaseModel):
    id: str = Field(description="ToolCall ID to approve or reject")
    action: str = Field(description="'approve' or 'reject'")
    arguments: dict | None = Field(default=None, description="Optional edited arguments")


class SubmitApprovalsRequest(BaseModel):
    approvals: list[ApprovalActionItem]
    model: str = Field(default=DEFAULT_MODEL)


class StartRunResponse(BaseModel):
    run_id: str = Field(description="Unique run ID")
    status: str = Field(description="Run status, e.g. 'started'")


class CancelRunResponse(BaseModel):
    status: str = Field(description="'cancelled' if run was active, 'not_active' otherwise")


class ResumeRunResponse(BaseModel):
    status: str = Field(description="'resumed'")


class RevertRunResponse(BaseModel):
    status: str = Field(description="'reverted'")
    git_ref: str = Field(description="The Git commit ref reverted to")


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=StartRunResponse)
async def start_run(
    request: StartRunRequest,
    response: Response,
    run_mgr: RunManager = Depends(get_run_manager),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Initialize and trigger a background execution run for an active session.

    Validates session existence, security policy mode, and step bounds.
    Creates a database Run record and launches the agent run loop asynchronously.

    Args:
        request: Run parameters including session ID, prompt, model, and policy.
        response: FastAPI Response object used to set Location header.
        run_mgr: Active RunManager instance.
        db: Active database session.
        settings: Application settings.

    Returns:
        StartRunResponse: Containing the unique run ID and 'started' status.
    """
    session_rec = db.get(DBSession, request.session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.policy_mode not in {"ask_all", "auto_edit", "full_auto"}:
        raise HTTPException(status_code=400, detail="policy_mode must be ask_all, auto_edit or full_auto")
    max_steps = request.max_steps if request.max_steps is not None else settings.max_steps
    if max_steps < 1 or max_steps > 200:
        raise HTTPException(status_code=400, detail="max_steps must be between 1 and 200")

    model_name = resolve_model(request.model, request.provider, settings)
    run_id = str(uuid.uuid4())
    run = Run(
        id=run_id,
        session_id=request.session_id,
        status="running",
        model=model_name,
        provider=(request.provider or settings.default_provider),
    )
    db.add(run)
    db.commit()

    try:
        await run_mgr.start_run(
            run_id=run_id,
            session_id=request.session_id,
            user_prompt=request.prompt,
            model_name=model_name,
            max_steps=max_steps,
            policy_mode=request.policy_mode,
            provider_name=request.provider,
        )
    except Exception as exc:
        # Never leave an orphan row claiming to be running.
        run.status = "failed"
        db.add(run)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start run: {exc}")

    response.headers["Location"] = f"/api/v1/runs/{run_id}"
    return {"run_id": run_id, "status": "started"}


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db_session)):
    """Retrieve status, metadata, and ordered tool calls for a specific run.

    Args:
        run_id: Unique UUID string identifying the run.
        db: Active database session dependency.

    Returns:
        dict: Serialized Run record and list of associated ToolCall records.
    """
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    tool_calls = db.exec(
        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at.asc())
    ).all()

    return {"run": run, "tool_calls": tool_calls}


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(run_id: str, run_mgr: RunManager = Depends(get_run_manager)):
    """Cancel an active agent run if currently executing or awaiting approval.

    Args:
        run_id: Unique UUID of the run to cancel.
        run_mgr: Active RunManager singleton instance.

    Returns:
        CancelRunResponse: Status indicating 'cancelled' or 'not_active'.
    """
    cancelled = await run_mgr.cancel_run(run_id)
    return {"status": "cancelled" if cancelled else "not_active"}


@router.post("/{run_id}/approvals", response_model=ResumeRunResponse)
async def submit_approvals(
    run_id: str,
    request: SubmitApprovalsRequest,
    run_mgr: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings),
):
    """Resume execution of an awaiting_approval run after user approval or rejection.

    Args:
        run_id: Unique UUID of the suspended run.
        request: Tool approval and rejection decisions with optional edited arguments.
        run_mgr: Active RunManager singleton instance.
        settings: Application configuration settings.

    Returns:
        ResumeRunResponse: Status confirming resumption.
    """
    try:
        await run_mgr.continue_run(
            run_id=run_id,
            approvals=[a.model_dump() for a in request.approvals],
            model_name=resolve_model(request.model, None, settings),
        )
        return {"status": "resumed"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{run_id}/revert", response_model=RevertRunResponse)
def revert_run_checkpoint(
    run_id: str,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Revert workspace to the pre-run snapshot checkpoint.

    Args:
        run_id: Unique UUID of the completed or cancelled run.
        db: Active database session dependency.
        settings: Application configuration settings.

    Returns:
        RevertRunResponse: Revert confirmation and target Git commit SHA.
    """
    from backend.app.agent.checkpoints import CheckpointManager
    from backend.app.db.models import Checkpoint, Project

    cp = db.exec(select(Checkpoint).where(Checkpoint.run_id == run_id)).first()
    if not cp or not cp.git_ref:
        raise HTTPException(
            status_code=404,
            detail="No checkpoint found for this run. Note that checkpoints require an initialized Git workspace.",
        )

    project = db.get(Project, cp.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    work_dir = settings.project_root(project.slug)
    if not CheckpointManager.is_git_workspace(work_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Project workspace '{project.slug}' is not an initialized Git repository; cannot revert.",
        )

    reverted = CheckpointManager.revert_run(work_dir, cp.git_ref)
    if not reverted:
        raise HTTPException(status_code=500, detail="Failed to revert workspace.")

    return {"status": "reverted", "git_ref": cp.git_ref}

