import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.db.cascade import (
    delete_session_records,
    has_active_runs,
    run_ids_for_sessions,
)
from backend.app.db.database import get_db_session
from backend.app.db.models import Message, Project, Session as DBSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    project_slug: str
    title: str = Field(default="New Thread")


class ForkSessionRequest(BaseModel):
    up_to_message_id: str | None = None
    new_title: str = Field(default="Forked Thread")


class UpdateTodoRequest(BaseModel):
    todos: list[dict]


@router.get("/by-project/{project_slug}")
def list_project_sessions(project_slug: str, db: Session = Depends(get_db_session)):
    """List all chat sessions associated with a specific project slug.

    Args:
        project_slug: The unique identifier slug of the project.
        db: Active database session dependency.

    Returns:
        dict: List of session records ordered from newest to oldest.
    """
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sessions = db.exec(
        select(DBSession)
        .where(DBSession.project_id == project.id)
        .order_by(DBSession.created_at.desc())
    ).all()
    return {"sessions": [s.model_dump() for s in sessions]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(request: CreateSessionRequest, response: Response, db: Session = Depends(get_db_session)):
    """Create a new conversational thread within a project.

    Args:
        request: Project slug and optional title for the new session.
        response: FastAPI Response object for Location header.
        db: Active database session dependency.

    Returns:
        dict: The created session record.
    """
    project = db.exec(select(Project).where(Project.slug == request.project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    new_sess = DBSession(project_id=project.id, title=request.title.strip() or "New Thread")
    db.add(new_sess)
    db.commit()
    db.refresh(new_sess)
    response.headers["Location"] = f"/api/v1/sessions/{new_sess.id}"
    return {"session": new_sess.model_dump()}


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    confirm: str = Query(..., description="Type the exact session ID to confirm deletion"),
    db: Session = Depends(get_db_session),
):
    """Delete one thread and its messages/runs/events while preserving the workspace.

    Args:
        session_id: The unique ID of the session to delete.
        confirm: Confirmation string that must match session_id.
        db: Active database session dependency.

    Returns:
        dict: Deletion confirmation and counts of cascaded records removed.
    """
    session_rec = db.get(DBSession, session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")
    if confirm != session_id:
        raise HTTPException(status_code=400, detail="Confirmation must match the session ID")

    run_ids = run_ids_for_sessions(db, [session_id])
    if has_active_runs(db, run_ids):
        raise HTTPException(
            status_code=409,
            detail="This thread has an active run. Cancel it before deleting the thread.",
        )

    stats = delete_session_records(db, [session_id])
    return {"status": "deleted", "session_id": session_id, "deleted": stats}


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db_session)):
    """Fetch session details, chronological message history, and active todo list.

    Args:
        session_id: Unique UUID of the session.
        db: Active database session dependency.

    Returns:
        dict: Session metadata, ordered list of messages, and parsed todo items.
    """
    session_rec = db.get(DBSession, session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    ).all()

    try:
        todos = json.loads(session_rec.todo_list_json)
    except Exception:
        todos = []

    return {
        "session": session_rec.model_dump(),
        "messages": [m.model_dump() for m in messages],
        "todos": todos,
    }


@router.post("/{session_id}/fork", status_code=status.HTTP_201_CREATED)
def fork_session(
    session_id: str, request: ForkSessionRequest, response: Response, db: Session = Depends(get_db_session)
):
    """Fork an existing thread up to an optional message ID into a new session.

    Args:
        session_id: Origin session to fork from.
        request: New session title and boundary message ID.
        response: FastAPI Response object for Location header.
        db: Active database session dependency.

    Returns:
        dict: The newly created forked session record and message copy count.
    """
    orig_session = db.get(DBSession, session_id)
    if not orig_session:
        raise HTTPException(status_code=404, detail="Original session not found")

    new_session = DBSession(
        project_id=orig_session.project_id,
        title=request.new_title,
        todo_list_json=orig_session.todo_list_json,
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Copy messages up to up_to_message_id
    messages = list(
        db.exec(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        ).all()
    )

    copied_count = 0
    for m in messages:
        copied_msg = Message(
            session_id=new_session.id,
            role=m.role,
            content=m.content,
            thinking=m.thinking,
            tool_calls_json=m.tool_calls_json,
            tool_call_id=m.tool_call_id,
            tool_name=m.tool_name,
            metrics_json=m.metrics_json,
        )
        db.add(copied_msg)
        copied_count += 1
        if request.up_to_message_id and m.id == request.up_to_message_id:
            break

    db.commit()
    response.headers["Location"] = f"/api/v1/sessions/{new_session.id}"
    return {"forked_session": new_session.model_dump(), "messages_copied": copied_count}


@router.post("/{session_id}/todos")
def update_session_todos(session_id: str, request: UpdateTodoRequest, db: Session = Depends(get_db_session)):
    """Update the persisted todo items list for a specific thread.

    Args:
        session_id: Unique UUID of the session.
        request: Structured list of updated todo item objects.
        db: Active database session dependency.

    Returns:
        dict: Status confirming update.
    """
    session_rec = db.get(DBSession, session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")

    session_rec.todo_list_json = json.dumps(request.todos)
    db.add(session_rec)
    db.commit()
    return {"status": "ok"}
