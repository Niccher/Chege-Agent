import shutil

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.db.cascade import (
    delete_project_records,
    has_active_runs,
    run_ids_for_sessions,
    session_ids_for_project,
)
from backend.app.db.database import get_db_session
from backend.app.db.models import Project, Session as DBSession
from backend.app.security.paths import sanitize_project_name

router = APIRouter(prefix="/projects", tags=["projects"])
logger = get_logger("api.projects")


class CreateProjectRequest(BaseModel):
    name: str = Field(description="Display name for project")
    goal: str = Field(default="")
    stack: str = Field(default="")
    notes: str = Field(default="")


class UpdateBrainRequest(BaseModel):
    goal: str = Field(default="")
    stack: str = Field(default="")
    notes: str = Field(default="")


@router.get("")
def list_projects(db: Session = Depends(get_db_session)):
    projects = db.exec(select(Project).order_by(Project.created_at.desc())).all()
    return {"projects": [p.model_dump() for p in projects]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    request: CreateProjectRequest,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    try:
        slug = sanitize_project_name(request.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = db.exec(select(Project).where(Project.slug == slug)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Project '{slug}' already exists.")

    # Prepare the workspace first so a DB failure cannot leave a project row
    # pointing at a directory that does not exist (and vice versa).
    import shutil
    import subprocess
    work_dir = settings.project_root(slug)
    created_dir = False
    try:
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)
            created_dir = True
        git_dir = work_dir / ".git"
        if not git_dir.exists():
            for argv in (
                ["git", "init"],
                ["git", "config", "user.name", "Chege Agent"],
                ["git", "config", "user.email", "agent@chege.local"],
                ["git", "commit", "--allow-empty", "-m", "Initial repository commit"],
            ):
                subprocess.run(argv, cwd=work_dir, capture_output=True, check=True)

        project = Project(
            name=request.name.strip(),
            slug=slug,
            brain_goal=request.goal,
            brain_stack=request.stack,
            brain_notes=request.notes,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        default_session = DBSession(project_id=project.id, title="Main Thread")
        db.add(default_session)
        db.commit()
    except subprocess.CalledProcessError as e:
        db.rollback()
        if created_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not initialize project workspace: {e}")
    except Exception as e:
        db.rollback()
        if created_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not create project: {e}")

    response.headers["Location"] = f"/api/v1/projects/{slug}"
    return {"project": project.model_dump(), "default_session_id": default_session.id}


@router.delete("/{project_slug}")
def delete_project(
    project_slug: str,
    confirm: str = Query(..., description="Type the exact project slug to confirm deletion"),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Permanently delete a project, its threads/runs and its workspace."""
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if confirm != project_slug:
        raise HTTPException(status_code=400, detail="Confirmation must match the project slug")

    session_ids = session_ids_for_project(db, project.id)
    run_ids = run_ids_for_sessions(db, session_ids)
    if has_active_runs(db, run_ids):
        raise HTTPException(
            status_code=409,
            detail="This project has an active run. Cancel it before deleting the project.",
        )

    stats = delete_project_records(db, project)
    removed_workspace = False
    workspace_error = None
    try:
        work_dir = settings.project_root(project_slug)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            removed_workspace = not work_dir.exists()
    except Exception as exc:
        # The DB deletion already committed; report the leftover workspace
        # instead of turning a successful data deletion into a 500.
        workspace_error = str(exc)
        logger.warning("Project %s deleted but workspace removal failed: %s", project_slug, exc)

    response = {
        "status": "deleted",
        "project_slug": project_slug,
        "deleted": stats,
        "workspace_removed": removed_workspace,
    }
    if workspace_error:
        response["workspace_error"] = workspace_error
    return response


@router.get("/{project_slug}")
def get_project(project_slug: str, db: Session = Depends(get_db_session)):
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump()}


@router.post("/{project_slug}/brain")
def update_project_brain(
    project_slug: str,
    request: UpdateBrainRequest,
    db: Session = Depends(get_db_session),
):
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.brain_goal = request.goal
    project.brain_stack = request.stack
    project.brain_notes = request.notes
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"status": "ok", "project": project.model_dump()}
