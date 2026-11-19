import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from backend.app.db.database import get_db_session
from backend.app.db.models import Message, Project, Session as DBSession
from backend.app.security.auth import verify_auth_token

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(verify_auth_token)])


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
    project = db.exec(select(Project).where(Project.slug == project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sessions = db.exec(
        select(DBSession)
        .where(DBSession.project_id == project.id)
        .order_by(DBSession.created_at.desc())
    ).all()
    return {"sessions": [s.model_dump() for s in sessions]}


@router.post("")
def create_session(request: CreateSessionRequest, db: Session = Depends(get_db_session)):
    project = db.exec(select(Project).where(Project.slug == request.project_slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    new_sess = DBSession(project_id=project.id, title=request.title.strip() or "New Thread")
    db.add(new_sess)
    db.commit()
    db.refresh(new_sess)
    return {"session": new_sess.model_dump()}


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db_session)):
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


@router.post("/{session_id}/fork")
def fork_session(session_id: str, request: ForkSessionRequest, db: Session = Depends(get_db_session)):
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
        )
        db.add(copied_msg)
        copied_count += 1
        if request.up_to_message_id and m.id == request.up_to_message_id:
            break

    db.commit()
    return {"forked_session": new_session.model_dump(), "messages_copied": copied_count}


@router.post("/{session_id}/todos")
def update_session_todos(session_id: str, request: UpdateTodoRequest, db: Session = Depends(get_db_session)):
    session_rec = db.get(DBSession, session_id)
    if not session_rec:
        raise HTTPException(status_code=404, detail="Session not found")

    session_rec.todo_list_json = json.dumps(request.todos)
    db.add(session_rec)
    db.commit()
    return {"status": "ok"}
