from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from backend.app.core.config import get_settings
from backend.app.main import create_app


@pytest.fixture
def test_client(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / "test_api.db"
    engine = create_engine(f"sqlite:///{test_db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    from backend.app.db.database import get_db_session
    def override_get_db():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "workdir", tmp_path / "workdir")
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_token", "test-secret-token")

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        yield client, "test-secret-token"


def test_healthz_unauthenticated(test_client):
    client, _ = test_client
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_auth_rejection(test_client):
    client, _ = test_client
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_project_crud_authenticated(test_client):
    client, token = test_client
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create project
    create_resp = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Demo Calculator", "goal": "Build CLI calc", "stack": "Python"},
    )
    assert create_resp.status_code == 200
    data = create_resp.json()
    assert data["project"]["slug"] == "Demo-Calculator"

    # 2. List projects
    list_resp = client.get("/api/projects", headers=headers)
    assert list_resp.status_code == 200
    projects = list_resp.json()["projects"]
    assert any(p["slug"] == "Demo-Calculator" for p in projects)

    # 3. List sessions for project
    sess_resp = client.get("/api/sessions/by-project/Demo-Calculator", headers=headers)
    assert sess_resp.status_code == 200
    sessions = sess_resp.json()["sessions"]
    assert len(sessions) >= 1
    assert sessions[0]["title"] == "Main Thread"
