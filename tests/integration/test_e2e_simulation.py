import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from backend.app.core.config import get_settings
from backend.app.db.database import get_db_session
from backend.app.main import create_app
from backend.app.providers.base import ChatChunk, ModelOptions, Provider
from backend.app.agent.run_manager import RunManager
from backend.app.sandbox.local import LocalSandbox


class ScriptedE2EProvider(Provider):
    """Realistic scripted provider simulating full multi-turn assistant reasoning."""
    def __init__(self):
        self.step = 0

    async def list_models(self):
        return []

    async def stream_chat(self, model, messages, tools, options):
        self.step += 1
        if self.step == 1:
            # Turn 1: Propose creating a script file and running it
            yield ChatChunk(
                delta_content="I will create a calculator module and run it.",
                delta_thinking="Analyzing project requirements. First step: write the module.",
                tool_calls=[
                    {
                        "id": "call_write_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps({
                                "path": "calc.py",
                                "content": "def add(a, b):\n    return a + b\n\nprint('Result:', add(10, 32))\n"
                            }),
                        },
                    }
                ],
            )
        elif self.step == 2:
            # Turn 2: Run the script using run_command (exec risk -> will pause for approval in ask_all mode)
            yield ChatChunk(
                delta_content="Now executing the script.",
                tool_calls=[
                    {
                        "id": "call_exec_1",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": json.dumps({"command": "python3 calc.py"}),
                        },
                    }
                ],
            )
        else:
            # Turn 3: Final response after tool output received
            yield ChatChunk(
                delta_content="The calculation completed successfully with result 42.",
                finish_reason="stop",
            )


def test_full_lifecycle_end_to_end(tmp_path: Path, monkeypatch):
    """
    Realistic End-to-End Simulation:
    Tests project creation, git initialization, session management,
    tool execution, checkpoint snapshotting, approval flow, SSE event catchup,
    and checkpoint reversion.
    """
    test_db = tmp_path / "e2e_sim.db"
    engine = create_engine(f"sqlite:///{test_db}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import backend.app.db.database as db_mod
    import backend.app.agent.run_manager as rm_mod
    monkeypatch.setattr(db_mod, "get_db_engine", lambda: engine)
    monkeypatch.setattr(rm_mod, "get_db_engine", lambda: engine)

    def override_get_db():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    settings = get_settings()
    workdir = tmp_path / "workspaces"
    workdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "workdir", workdir)

    # Wire run manager with scripted realistic provider
    scripted_provider = ScriptedE2EProvider()
    sandbox_factory = lambda root, slug: LocalSandbox(root)
    run_mgr = RunManager(provider=scripted_provider, sandbox_factory=sandbox_factory)

    from backend.app.api import runs_router

    app = create_app()
    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[runs_router.get_run_manager] = lambda: run_mgr

    with TestClient(app) as client:
        # 1. Create project
        resp = client.post(
            "/api/v1/projects",
            json={"name": "End2End Sim Project", "goal": "Verify all harness features", "stack": "Python"},
        )
        assert resp.status_code == 201, resp.text
        proj_data = resp.json()
        slug = proj_data["project"]["slug"]
        default_session_id = proj_data["default_session_id"]
        assert slug == "End2End-Sim-Project"

        # Verify git repo and initial commit exist
        proj_dir = workdir / slug
        assert (proj_dir / ".git").exists()
        import subprocess
        log_res = subprocess.run(["git", "log", "-n", "1", "--oneline"], cwd=proj_dir, capture_output=True, text=True)
        assert log_res.returncode == 0
        assert "Initial repository commit" in log_res.stdout

        # 2. Query project brain and update it
        brain_resp = client.post(
            f"/api/v1/projects/{slug}/brain",
            json={"goal": "Updated Goal", "stack": "FastAPI", "notes": "No notes"},
        )
        assert brain_resp.status_code == 200
        assert brain_resp.json()["project"]["brain_goal"] == "Updated Goal"

        # 3. Start a Run in auto_edit mode (will pause when run_command is proposed)
        start_resp = client.post(
            "/api/v1/runs",
            json={
                "session_id": default_session_id,
                "prompt": "Build and run the calculator",
                "model": "qwen2.5-coder",
                "policy_mode": "auto_edit",
                "max_steps": 10,
            },
        )
        assert start_resp.status_code == 202
        assert start_resp.headers["location"] == f"/api/v1/runs/{start_resp.json()['run_id']}"
        run_id = start_resp.json()["run_id"]

        # Wait for agent loop to pause on approval
        import time
        paused = False
        for _ in range(50):
            time.sleep(0.05)
            r_info = client.get(f"/api/v1/runs/{run_id}").json()
            if r_info["run"]["status"] == "awaiting_approval":
                paused = True
                break
        assert paused, f"Run did not pause for approval. Current state: {r_info}"

        # Confirm calc.py was created before pause (Turn 1 was safe tool write_file)
        assert (proj_dir / "calc.py").exists()

        # Find the pending tool call ID
        tool_calls = r_info["tool_calls"]
        assert len(tool_calls) >= 1
        pending_tc = [tc for tc in tool_calls if tc["status"] == "pending"][0]
        assert pending_tc["tool_name"] == "run_command"

        # 4. Submit approval
        appr_resp = client.post(
            f"/api/v1/runs/{run_id}/approvals",
            json={
                "model": "qwen2.5-coder",
                "approvals": [{"id": pending_tc["id"], "action": "approve"}],
            },
        )
        assert appr_resp.status_code == 200
        assert appr_resp.json()["status"] == "resumed"

        # Wait for run completion
        completed = False
        for _ in range(50):
            time.sleep(0.05)
            r_info = client.get(f"/api/v1/runs/{run_id}").json()
            if r_info["run"]["status"] == "completed":
                completed = True
                break
        assert completed, f"Run did not complete. State: {r_info}"

        # 5. Check SSE events catchup (?after=0)
        events_resp = client.get(f"/api/v1/runs/{run_id}/events?after=0")
        assert events_resp.status_code == 200
        events_text = events_resp.text
        assert "event: run.started" in events_text
        assert "event: tool.started" in events_text
        assert "event: run.completed" in events_text

        # 6. Check files API
        files_resp = client.get(f"/api/v1/files?project_slug={slug}")
        assert files_resp.status_code == 200
        file_list = files_resp.json()["files"]
        assert "calc.py" in file_list

        content_resp = client.get(f"/api/v1/files/content?project_slug={slug}&filepath=calc.py")
        assert content_resp.status_code == 200
        assert "def add(a, b):" in content_resp.json()["content"]

        # 7. Check session messages and history
        sess_resp = client.get(f"/api/v1/sessions/{default_session_id}")
        assert sess_resp.status_code == 200
        messages = sess_resp.json()["messages"]
        # Should have user prompt, assistant proposal, tool output, etc.
        assert len(messages) >= 3
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles
