from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.core.config import Settings, get_settings
from backend.app.db.database import get_db_session
from backend.app.db.models import Project, Session as DBSession
from backend.app.security.auth import verify_auth_token
from backend.app.security.paths import sanitize_project_name

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(verify_auth_token)])


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


@router.post("")
def create_project(
    request: CreateProjectRequest,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    try:
        slug = sanitize_project_name(request.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = db.exec(select(Project).where(Project.slug == slug)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Project '{slug}' already exists.")

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

    # Initialize directory and git repo in workspace
    work_dir = settings.workdir / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    git_dir = work_dir / ".git"
    if not git_dir.exists():
        import subprocess
        subprocess.run(["git", "init"], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Chege Agent"], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "agent@chege.local"], cwd=work_dir, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "Initial repository commit"], cwd=work_dir, capture_output=True)


    # Create default session for project
    default_session = DBSession(project_id=project.id, title="Main Thread")
    db.add(default_session)
    db.commit()

    return {"project": project.model_dump(), "default_session_id": default_session.id}


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
