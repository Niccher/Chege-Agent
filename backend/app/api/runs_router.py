import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.agent.run_manager import RunManager
from backend.app.core.config import Settings, get_settings
from backend.app.db.database import get_db_session
from backend.app.db.models import Run, Session as DBSession, ToolCall
from backend.app.providers.ollama import OllamaProvider
from backend.app.providers.openai_compat import OpenAICompatProvider
from backend.app.sandbox.docker import DockerSandbox
from backend.app.sandbox.local import LocalSandbox
from backend.app.security.auth import verify_auth_token

router = APIRouter(prefix="/api/runs", tags=["runs"], dependencies=[Depends(verify_auth_token)])

_run_manager = None


def get_run_manager(settings: Settings = Depends(get_settings)) -> RunManager:
    global _run_manager
    if _run_manager is None:
        if settings.default_provider == "openai" and settings.openai_api_key:
            provider = OpenAICompatProvider(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
        else:
            provider = OllamaProvider(base_url=settings.ollama_url)

        def sandbox_factory(workspace_root, slug):
            if settings.sandbox_backend == "docker":
                return DockerSandbox(workspace_root, slug, image=settings.default_sandbox_image)
            return LocalSandbox(workspace_root)

        _run_manager = RunManager(provider=provider, sandbox_factory=sandbox_factory)
    return _run_manager


class StartRunRequest(BaseModel):
    session_id: str
    prompt: str = Field(description="User prompt / instruction")
    model: str = Field(default="qwen2.5-coder:latest")
    policy_mode: str = Field(default="auto_edit", description="ask_all | auto_edit | full_auto")
    max_steps: int = Field(default=50)


class ApprovalActionItem(BaseModel):
    id: str = Field(description="ToolCall ID to approve or reject")
    action: str = Field(description="'approve' or 'reject'")
    arguments: dict | None = Field(default=None, description="Optional edited arguments")


class SubmitApprovalsRequest(BaseModel):
    approvals: list[ApprovalActionItem]
    model: str = Field(default="qwen2.5-coder:latest")


@router.post("")
async def start_run(
    request: StartRunRequest,
    run_mgr: RunManager = Depends(get_run_manager),
    db: Session = Depends(get_db_session),
):
    session_rec = db.get(DBSession, request.session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")

    run_id = str(uuid.uuid4())
    run = Run(
        id=run_id,
        session_id=request.session_id,
        status="running",
        model=request.model,
    )
    db.add(run)
    db.commit()

    await run_mgr.start_run(
        run_id=run_id,
        session_id=request.session_id,
        user_prompt=request.prompt,
        model_name=request.model,
        max_steps=request.max_steps,
        policy_mode=request.policy_mode,
    )

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
):
    try:
        await run_mgr.continue_run(
            run_id=run_id,
            approvals=[a.model_dump() for a in request.approvals],
            model_name=request.model,
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

    work_dir = settings.workdir / project.slug
    reverted = CheckpointManager.revert_run(work_dir, cp.git_ref)
    if not reverted:
        raise HTTPException(status_code=500, detail="Failed to revert workspace.")

    return {"status": "reverted", "git_ref": cp.git_ref}

