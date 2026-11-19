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

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as client:
        yield client


def test_healthz(test_client):
    client = test_client
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_is_locally_accessible(test_client):
    client = test_client
    resp = client.get("/api/v1/projects")
    assert resp.status_code == 200


def test_project_crud(test_client):
    client = test_client

    # 1. Create project
    create_resp = client.post(
        "/api/v1/projects",
        json={"name": "Demo Calculator", "goal": "Build CLI calc", "stack": "Python"},
    )
    assert create_resp.status_code == 201
    assert create_resp.headers["location"] == "/api/v1/projects/Demo-Calculator"
    data = create_resp.json()
    assert data["project"]["slug"] == "Demo-Calculator"

    # 2. List projects
    list_resp = client.get("/api/v1/projects")
    assert list_resp.status_code == 200
    projects = list_resp.json()["projects"]
    assert any(p["slug"] == "Demo-Calculator" for p in projects)

    # 3. List sessions for project
    sess_resp = client.get("/api/v1/sessions/by-project/Demo-Calculator")
    assert sess_resp.status_code == 200
    sessions = sess_resp.json()["sessions"]
    assert len(sessions) >= 1
    assert sessions[0]["title"] == "Main Thread"
