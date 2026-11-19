"""Safe deletion helpers for local projects, threads and their dependent rows.

SQLite foreign keys are enabled, but the schema does not define ON DELETE
CASCADE: deletion must remove runs, events, messages, tool calls, grants and
checkpoints explicitly, in dependency order.
"""

from sqlalchemy import delete
from sqlmodel import Session, select

from backend.app.db.models import (
    ApprovalPolicy,
    Checkpoint,
    Event,
    Message,
    Project,
    Run,
    Session as DBSession,
    ToolCall,
    ToolGrant,
)


ACTIVE_RUN_STATES = ("running", "awaiting_approval")


def session_ids_for_project(db: Session, project_id: str) -> list[str]:
    return list(
        db.exec(select(DBSession.id).where(DBSession.project_id == project_id)).all()
    )


def run_ids_for_sessions(db: Session, session_ids: list[str]) -> list[str]:
    if not session_ids:
        return []
    return list(
        db.exec(select(Run.id).where(Run.session_id.in_(session_ids))).all()
    )


def has_active_runs(db: Session, run_ids: list[str]) -> bool:
    if not run_ids:
        return False
    active = db.exec(
        select(Run.id)
        .where(Run.id.in_(run_ids))
        .where(Run.status.in_(ACTIVE_RUN_STATES))
    ).first()
    return active is not None


def delete_session_records(db: Session, session_ids: list[str], commit: bool = True) -> dict:
    """Delete sessions and all run/message/tool data attached to them."""
    run_ids = run_ids_for_sessions(db, session_ids)
    try:
        if run_ids:
            db.execute(delete(Event).where(Event.run_id.in_(run_ids)))
            db.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
            db.execute(delete(ToolGrant).where(ToolGrant.run_id.in_(run_ids)))
            db.execute(delete(Checkpoint).where(Checkpoint.run_id.in_(run_ids)))
            db.execute(delete(Run).where(Run.id.in_(run_ids)))
        if session_ids:
            db.execute(delete(Message).where(Message.session_id.in_(session_ids)))
            db.execute(delete(DBSession).where(DBSession.id.in_(session_ids)))
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    return {"sessions": len(session_ids), "runs": len(run_ids)}


def delete_project_records(db: Session, project: Project) -> dict:
    """Delete a project, all of its threads, and project-scoped records."""
    session_ids = session_ids_for_project(db, project.id)
    try:
        stats = delete_session_records(db, session_ids, commit=False)
        db.execute(delete(Checkpoint).where(Checkpoint.project_id == project.id))
        db.execute(delete(ApprovalPolicy).where(ApprovalPolicy.project_id == project.id))
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return stats
