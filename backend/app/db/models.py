from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime (ENG-09)."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    settings_json: str = Field(default="{}")
    brain_goal: str = Field(default="")
    brain_stack: str = Field(default="")
    brain_notes: str = Field(default="")


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    project_id: str = Field(index=True, foreign_key="projects.id")
    title: str = Field(default="New Session")
    status: str = Field(default="active")  # active, archived
    todo_list_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    session_id: str = Field(index=True, foreign_key="sessions.id")
    role: str = Field(index=True)  # system, user, assistant, tool
    content: str = Field(default="")
    thinking: Optional[str] = Field(default=None)
    tool_calls_json: Optional[str] = Field(default=None)
    tool_call_id: Optional[str] = Field(default=None, index=True)  # AGT-02
    tool_name: Optional[str] = Field(default=None)
    metrics_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    session_id: str = Field(index=True, foreign_key="sessions.id")
    status: str = Field(default="running", index=True)  # running, awaiting_approval, completed, failed, cancelled, stalled
    model: str = Field(default="")
    provider: str = Field(default="")
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    duration_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = Field(default=None)


class ToolCall(SQLModel, table=True):
    __tablename__ = "tool_calls"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.id")
    tool_name: str = Field(index=True)
    arguments_json: str = Field(default="{}")
    status: str = Field(default="proposed", index=True)  # proposed, pending, approved, rejected, executing, completed, failed
    risk: str = Field(default="read")  # read, write, exec, network
    result: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    edited_by_user: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.id")
    seq: int = Field(index=True)  # strictly monotonic sequence number per run (RT-01)
    event_type: str = Field(index=True)
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utc_now)


class ToolSetting(SQLModel, table=True):
    __tablename__ = "tool_settings"

    tool_name: str = Field(primary_key=True)
    enabled: bool = Field(default=True)
    grant_mode: str = Field(default="none")  # none | prompt_once
    updated_at: datetime = Field(default_factory=utc_now)


class ToolGrant(SQLModel, table=True):
    __tablename__ = "tool_grants"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.id")
    tool_name: str = Field(index=True)
    scope: str = Field(default="run")  # run | once
    status: str = Field(default="granted", index=True)  # granted | consumed | revoked
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: Optional[datetime] = Field(default=None)


class ApprovalPolicy(SQLModel, table=True):
    __tablename__ = "approval_policies"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    project_id: str = Field(index=True, foreign_key="projects.id")
    tool_name: str = Field(index=True)
    risk: str = Field(default="read")
    action: str = Field(default="ask")  # allow, ask, deny


class Checkpoint(SQLModel, table=True):
    __tablename__ = "checkpoints"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.id")
    project_id: str = Field(index=True, foreign_key="projects.id")
    git_ref: str = Field(default="")
    summary: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
