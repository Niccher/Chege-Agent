from pathlib import Path
import subprocess
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.core.config import Settings, get_settings
from backend.app.db.database import get_db_session
from backend.app.db.models import Project
from backend.app.security.auth import verify_auth_token
from backend.app.security.paths import resolve_in

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(verify_auth_token)])


class CommitRequest(BaseModel):
    project_slug: str
    message: str = Field(default="Agent update")


@router.get("")
def list_workspace_files(
    project_slug: str,
    directory: str = Query(default="."),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
):
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    work_dir = settings.workdir / project_slug
    try:
        target = resolve_in(work_dir, directory)
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not target.exists():
        return {"files": []}

    files: list[str] = []
    for p in target.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_file():
            rel = p.relative_to(work_dir)
            files.append(str(rel).replace("\\", "/"))

    return {"files": sorted(files)}


@router.get("/content")
def get_file_content(
    project_slug: str,
    filepath: str,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
):
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    work_dir = settings.workdir / project_slug
    try:
        full_path = resolve_in(work_dir, filepath)
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if full_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")

    if full_path.stat().st_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large to display directly in editor (exceeds 5MB)")

    with open(full_path, "rb") as f:
        header_chunk = f.read(4096)
        if b"\x00" in header_chunk:
            raise HTTPException(status_code=400, detail="Binary files cannot be viewed in text editor")

    content = full_path.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "filepath": filepath}


@router.get("/diff")
def get_workspace_diff(
    project_slug: str,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
):
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    work_dir = settings.workdir / project_slug
    # Non-destructive diff (TL-09)
    res = subprocess.run(["git", "diff", "HEAD"], cwd=work_dir, capture_output=True, text=True)
    return {"diff": res.stdout}


@router.post("/commit")
def commit_workspace(
    request: CommitRequest,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db_session),
):
    project = db.exec(select(Project).where(Project.slug == request.project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    work_dir = settings.workdir / request.project_slug
    subprocess.run(["git", "add", "."], cwd=work_dir, capture_output=True)
    res = subprocess.run(["git", "commit", "-m", request.message], cwd=work_dir, capture_output=True, text=True)
    return {"status": "success", "output": res.stdout or res.stderr}
