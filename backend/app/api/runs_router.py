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
    global _run_manager
    provider = get_provider(settings=settings)

    def sandbox_factory(workspace_root, slug):
        if settings.sandbox_backend == "docker":
            return DockerSandbox(
                workspace_root,
                slug,
                image=settings.default_sandbox_image,
                docker_host=settings.docker_socket_proxy,
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
    """Use the operator's selected local model when no explicit one is given."""
    if name and name != DEFAULT_MODEL:
        return name
    target = (provider or settings.default_provider).lower()
    if target == "ollama" and settings.ollama_model:
        return settings.ollama_model
    if target == "llama_cpp" and settings.llamacpp_model:
        return settings.llamacpp_model
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


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    request: StartRunRequest,
    response: Response,
    run_mgr: RunManager = Depends(get_run_manager),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
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
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    tool_calls = db.exec(
        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at.asc())
    ).all()

    return {"run": run, "tool_calls": tool_calls}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, run_mgr: RunManager = Depends(get_run_manager)):
    cancelled = await run_mgr.cancel_run(run_id)
    return {"status": "cancelled" if cancelled else "not_active"}


@router.post("/{run_id}/approvals")
async def submit_approvals(
    run_id: str,
    request: SubmitApprovalsRequest,
    run_mgr: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings),
):
    try:
        await run_mgr.continue_run(
            run_id=run_id,
            approvals=[a.model_dump() for a in request.approvals],
            model_name=resolve_model(request.model, None, settings),
        )
        return {"status": "resumed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{run_id}/revert")
def revert_run_checkpoint(
    run_id: str,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    from backend.app.agent.checkpoints import CheckpointManager
    from backend.app.db.models import Checkpoint, Project

    cp = db.exec(select(Checkpoint).where(Checkpoint.run_id == run_id)).first()
    if not cp or not cp.git_ref:
        raise HTTPException(status_code=404, detail="No checkpoint found for this run.")

    project = db.get(Project, cp.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    work_dir = settings.project_root(project.slug)
    reverted = CheckpointManager.revert_run(work_dir, cp.git_ref)
    if not reverted:
        raise HTTPException(status_code=500, detail="Failed to revert workspace.")

    return {"status": "reverted", "git_ref": cp.git_ref}

