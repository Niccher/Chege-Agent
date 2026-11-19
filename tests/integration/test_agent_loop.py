import asyncio
import json
from pathlib import Path
from typing import AsyncIterator
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from backend.app.agent.run_manager import RunManager
from backend.app.db.models import Message, Project, Run, Session as DBSession, ToolCall
from backend.app.providers.base import ChatChunk, InternalMessage, ModelInfo, ModelOptions, Provider
from backend.app.sandbox.local import LocalSandbox


class FakeScriptedProvider(Provider):
    """Deterministic scripted mock provider for testing the agent loop without external LLMs."""

    def __init__(self, script: list[list[ChatChunk]]):
        self.script = script
        self.call_count = 0

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="fake-model", name="fake-model", provider="fake")]

    async def stream_chat(
        self,
        model: str,
        messages: list[InternalMessage],
        tools: list[dict],
        options: ModelOptions,
    ) -> AsyncIterator[ChatChunk]:
        if self.call_count < len(self.script):
            chunks = self.script[self.call_count]
            self.call_count += 1
            for chunk in chunks:
                yield chunk
        else:
            yield ChatChunk(delta_content="Finished all scripted turns.")


@pytest.fixture
def setup_test_app(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{test_db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import backend.app.db.database as db_mod
    import backend.app.agent.run_manager as rm_mod
    monkeypatch.setattr(db_mod, "get_db_engine", lambda: engine)
    monkeypatch.setattr(rm_mod, "get_db_engine", lambda: engine)

    from backend.app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "workdir", tmp_path / "workdir")

    with Session(engine) as db:
        proj = Project(name="Test Scripted", slug="test-scripted")
        db.add(proj)
        db.commit()
        db.refresh(proj)

        sess = DBSession(project_id=proj.id, title="Test Session")
        db.add(sess)
        db.commit()
        db.refresh(sess)

        yield proj, sess, tmp_path, engine


@pytest.mark.asyncio
async def test_agent_loop_auto_executes_safe_tools(setup_test_app):
    proj, sess, tmp_path, engine = setup_test_app
    workspace_root = tmp_path / "workdir" / proj.slug
    workspace_root.mkdir(parents=True, exist_ok=True)

    # Turn 1: Model proposes write_file
    # Turn 2: Model returns final response
    script = [
        [
            ChatChunk(
                delta_content="Creating the configuration file.",
                tool_calls=[{
                    "id": "tc_1",
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "config.json", "content": '{"port": 8080}'},
                    },
                }],
            )
        ],
        [
            ChatChunk(delta_content="Done! The config file has been written.")
        ],
    ]

    provider = FakeScriptedProvider(script)
    run_mgr = RunManager(provider=provider, sandbox_factory=lambda root, slug: LocalSandbox(root))

    run_id = "test-run-1"
    with Session(engine) as db:
        db.add(Run(id=run_id, session_id=sess.id, status="running"))
        db.commit()

    await run_mgr._execute_loop(
        run_id=run_id,
        session_id=sess.id,
        user_prompt="Create config.json",
        model_name="fake-model",
        max_steps=10,
        policy_mode="auto_edit",
        cancel_evt=asyncio.Event(),
    )

    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert run.completed_at is not None

        messages = list(db.exec(select(Message).where(Message.session_id == sess.id)).all())
        # Should have: user msg, assistant msg with tool_calls, tool result msg, final assistant msg
        assert len(messages) >= 4

        # Verify tool result has tool_call_id
        tool_results = [m for m in messages if m.role == "tool"]
        assert len(tool_results) == 1
        assert tool_results[0].tool_name == "write_file"
        assert tool_results[0].tool_call_id == "tc_1"

        final_assistant = [m for m in messages if m.role == "assistant" and not m.tool_calls_json][-1]
        assert final_assistant.metrics_json

        # Auto-approved calls are also persisted as an audit trail.
        records = list(db.exec(select(ToolCall).where(ToolCall.run_id == run_id)).all())
        assert len(records) == 1
        assert records[0].tool_name == "write_file"
        assert records[0].status == "completed"
        assert "Written" in (records[0].result or "")

    # Completed runs must not retain the provider instance for the process lifetime.
    assert run_id not in run_mgr._providers

    # Verify file was created on disk
    created_file = workspace_root / "config.json"
    assert created_file.exists()
    assert '{"port": 8080}' in created_file.read_text()


@pytest.mark.asyncio
async def test_agent_loop_pauses_for_high_risk_approval(setup_test_app):
    proj, sess, tmp_path, engine = setup_test_app
    workspace_root = tmp_path / "workdir" / proj.slug
    workspace_root.mkdir(parents=True, exist_ok=True)

    # Turn 1: Model proposes run_command (exec risk)
    script = [
        [
            ChatChunk(
                delta_content="Running a system command.",
                tool_calls=[{
                    "id": "tc_exec_1",
                    "function": {
                        "name": "run_command",
                        "arguments": {"command": "rm -rf some_dir"},
                    },
                }],
            )
        ],
        [
            ChatChunk(delta_content="Command finished.")
        ],
    ]

    provider = FakeScriptedProvider(script)
    run_mgr = RunManager(provider=provider, sandbox_factory=lambda root, slug: LocalSandbox(root))

    run_id = "test-run-exec"
    with Session(engine) as db:
        db.add(Run(id=run_id, session_id=sess.id, status="running"))
        db.commit()

    await run_mgr._execute_loop(
        run_id=run_id,
        session_id=sess.id,
        user_prompt="Clean directory",
        model_name="fake-model",
        max_steps=10,
        policy_mode="auto_edit",  # exec risk requires approval
        cancel_evt=asyncio.Event(),
    )

    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run.status == "awaiting_approval"

        pending_calls = list(db.exec(select(ToolCall).where(ToolCall.run_id == run_id)).all())
        assert len(pending_calls) == 1
        assert pending_calls[0].tool_name == "run_command"
        assert pending_calls[0].status == "pending"

    # Awaiting-approval runs keep their provider for the resume path.
    assert run_id in run_mgr._providers

    # A run paused for approval must still be cancellable.
    assert await run_mgr.cancel_run(run_id) is True
    with Session(engine) as db:
        cancelled = db.get(Run, run_id)
        assert cancelled.status == "cancelled"
        assert cancelled.completed_at is not None


@pytest.mark.asyncio
async def test_agent_loop_saves_thinking_and_metrics(setup_test_app):
    proj, sess, tmp_path, engine = setup_test_app
    workspace_root = tmp_path / "workdir" / proj.slug
    workspace_root.mkdir(parents=True, exist_ok=True)

    provider = FakeScriptedProvider([[
        ChatChunk(delta_thinking="Let me think about this."),
        ChatChunk(delta_content="The answer is 42."),
    ]])
    run_mgr = RunManager(provider=provider, sandbox_factory=lambda root, slug: LocalSandbox(root))

    run_id = "test-run-thinking"
    with Session(engine) as db:
        db.add(Run(id=run_id, session_id=sess.id, status="running"))
        db.commit()

    await run_mgr._execute_loop(
        run_id=run_id,
        session_id=sess.id,
        user_prompt="Think then answer",
        model_name="fake-model",
        max_steps=5,
        policy_mode="auto_edit",
        cancel_evt=asyncio.Event(),
    )

    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run.status == "completed"
        assert run.completed_at is not None
        assistant = [
            m for m in db.exec(select(Message).where(Message.session_id == sess.id)).all()
            if m.role == "assistant"
        ][-1]
        assert assistant.thinking == "Let me think about this."
        assert assistant.content == "The answer is 42."
        metrics = json.loads(assistant.metrics_json)
        assert "thinking_ms" in metrics
        assert metrics["run_id"] == run_id
