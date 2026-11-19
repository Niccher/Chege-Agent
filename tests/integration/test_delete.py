import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine, select

from backend.app.core.config import get_settings
from backend.app.db.database import get_db_session
from backend.app.db.models import (
    Checkpoint,
    Event,
    Message,
    Project,
    Run,
    Session as DBSession,
    ToolCall,
    ToolGrant,
)
from backend.app.main import create_app


@pytest.fixture
def delete_app(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'delete.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "workdir", tmp_path / "workdir")

    def override_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db_session] = override_db
    return app, engine, tmp_path / "workdir"


def _seed_project(engine, slug: str, sessions: int = 1):
    with Session(engine) as db:
        project = Project(name=slug.title(), slug=slug)
        db.add(project)
        db.commit()
        db.refresh(project)
        session_ids = []
        for index in range(sessions):
            session = DBSession(project_id=project.id, title=f"Thread {index + 1}")
            db.add(session)
            db.commit()
            db.refresh(session)
            session_ids.append(session.id)
            run = Run(id=f"run-{slug}-{index}", session_id=session.id, status="completed")
            db.add(run)
            db.add(Message(session_id=session.id, role="user", content="hello"))
            db.add(Event(run_id=run.id, seq=1, event_type="run.started", payload_json=json.dumps({})))
            db.add(ToolCall(run_id=run.id, tool_name="read_file", status="completed"))
            db.add(ToolGrant(run_id=run.id, tool_name="read_file"))
            db.add(Checkpoint(run_id=run.id, project_id=project.id, git_ref="abc"))
        db.commit()
        return project.id, session_ids


@pytest.mark.asyncio
async def test_delete_project_removes_database_rows_and_workspace(delete_app):
    app, engine, workdir = delete_app
    project_id, session_ids = _seed_project(engine, "delete-me", sessions=2)
    project_dir = workdir / "delete-me"
    project_dir.mkdir(parents=True)
    (project_dir / "file.txt").write_text("x", encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/v1/projects/delete-me?confirm=delete-me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deleted"
    assert resp.json()["workspace_removed"] is True

    with Session(engine) as db:
        assert db.get(Project, project_id) is None
        assert not db.exec(select(DBSession).where(DBSession.project_id == project_id)).all()
        assert not db.exec(select(Run).where(Run.session_id.in_(session_ids))).all()
        assert not db.exec(select(Message).where(Message.session_id.in_(session_ids))).all()
        assert not db.exec(select(Event).where(Event.run_id.like("run-delete-me-%"))).all()
    assert not project_dir.exists()


@pytest.mark.asyncio
async def test_delete_thread_keeps_project_and_workspace(delete_app):
    app, engine, workdir = delete_app
    project_id, session_ids = _seed_project(engine, "keep-me", sessions=2)
    project_dir = workdir / "keep-me"
    project_dir.mkdir(parents=True)
    (project_dir / "file.txt").write_text("x", encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/v1/sessions/{session_ids[0]}?confirm={session_ids[0]}"
        )
    assert resp.status_code == 200, resp.text

    with Session(engine) as db:
        assert db.get(Project, project_id) is not None
        assert db.get(DBSession, session_ids[0]) is None
        assert db.get(DBSession, session_ids[1]) is not None
        assert not db.exec(select(Message).where(Message.session_id == session_ids[0])).all()
        assert db.exec(select(Message).where(Message.session_id == session_ids[1])).all()
    assert project_dir.exists()


@pytest.mark.asyncio
async def test_delete_requires_matching_confirmation(delete_app):
    app, engine, _ = delete_app
    _seed_project(engine, "confirm-me", sessions=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/v1/projects/confirm-me?confirm=wrong")
    assert resp.status_code == 400
