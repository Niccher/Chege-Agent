"""Read-only activity feed for tool calls.

The run loop stores every executed tool call as a ``tool.started`` /
``tool.completed`` event pair. This router pairs those events so the Tools
console can show a persistent history instead of only the live SSE feed.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from backend.app.db.database import get_db_session
from backend.app.db.models import Event, Project, Run, Session as DBSession

router = APIRouter(prefix="/activity", tags=["activity"])


def _payload(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _short(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def summarize_tool_call(tool: str, args: dict) -> str:
    """Turn a raw tool call into a human-readable one-line action."""
    name = (tool or "").strip()
    path = _short(args.get("path") or args.get("filepath") or "")
    if name == "write_file":
        return f"Wrote file {path or '(unknown)'}"
    if name == "edit_file":
        return f"Edited file {path or '(unknown)'}"
    if name == "delete_file":
        return f"Deleted file {path or '(unknown)'}"
    if name == "read_file":
        return f"Read file {path or '(unknown)'}"
    if name == "list_files":
        return f"Listed {args.get('directory') or '.'}"
    if name == "run_command":
        return f"Ran command: {_short(args.get('command'), 160)}"
    if name == "process_start":
        return f"Started process {args.get('name') or args.get('command') or '(unknown)'}"
    if name == "process_output":
        return f"Read output from process {args.get('process_id') or '(unknown)'}"
    if name == "process_kill":
        return f"Stopped process {args.get('process_id') or '(unknown)'}"
    if name == "process_list":
        return "Listed background processes"
    if name == "grep":
        pattern = _short(args.get("pattern"), 80)
        return f"Searched {args.get('path') or '.'} for “{pattern}”"
    if name == "git_diff":
        return f"Viewed git diff{' for ' + path if path else ''}"
    if name == "git_status":
        return "Checked git status"
    if name == "git_log":
        return "Viewed git log"
    if name == "git_commit":
        return f"Committed changes: {_short(args.get('message'), 100)}"
    if name == "memory_update":
        return f"Updated project memory ({args.get('section') or 'notes'})"
    if name == "ask_user":
        return f"Asked you: {_short(args.get('question'), 120)}"
    if name == "todo_write":
        todos = args.get("todos") or []
        return f"Updated the task plan ({len(todos)} item{'s' if len(todos) != 1 else ''})"
    if name == "web_fetch":
        return f"Fetched {_short(args.get('url'), 140)}"
    if name == "web_search":
        return f"Searched the web: {_short(args.get('query'), 120)}"
    return name or "Tool call"


def _result_status(result: str) -> str:
    text = (result or "").strip()
    if text.upper().startswith("ERROR"):
        return "error"
    if text.startswith("Exit code:") and not text.startswith("Exit code: 0"):
        return "error"
    return "completed"


@router.get("/tools")
def list_tool_activity(
    limit: int = Query(default=80, ge=1, le=250),
    project_slug: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
):
    """Return recent tool calls with timestamps, context and result previews."""
    statement = (
        select(Event, Run, DBSession, Project)
        .join(Run, Event.run_id == Run.id)
        .join(DBSession, Run.session_id == DBSession.id)
        .join(Project, DBSession.project_id == Project.id)
        .where(Event.event_type == "tool.started")
    )
    if project_slug:
        statement = statement.where(Project.slug == project_slug)
    statement = statement.order_by(Event.created_at.desc()).limit(limit)

    rows = list(db.exec(statement).all())
    if not rows:
        return {"activity": [], "count": 0}

    run_ids = {run.id for _event, run, _session, _project in rows}
    events = list(
        db.exec(
            select(Event)
            .where(Event.run_id.in_(run_ids))
            .where(Event.event_type.in_(["tool.started", "tool.completed"]))
            .order_by(Event.run_id, Event.seq)
        ).all()
    )
    by_run: dict[str, list[Event]] = {}
    for event in events:
        by_run.setdefault(event.run_id, []).append(event)

    activity = []
    for start_event, run, session, project in rows:
        start = _payload(start_event.payload_json)
        tool = str(start.get("tool") or "")
        args = start.get("arguments") if isinstance(start.get("arguments"), dict) else {}
        completion = None
        for event in by_run.get(run.id, []):
            if event.seq <= start_event.seq or event.event_type != "tool.completed":
                continue
            data = _payload(event.payload_json)
            if str(data.get("tool") or "") == tool:
                completion = (event, data)
                break

        result = ""
        status = "running"
        completed_at = None
        duration_ms = None
        if completion:
            completion_event, completion_data = completion
            result = str(completion_data.get("result") or "")
            status = _result_status(result)
            completed_at = completion_event.created_at
            duration_ms = int((completion_event.created_at - start_event.created_at).total_seconds() * 1000)

        activity.append({
            "id": f"{run.id}:{start_event.seq}",
            "run_id": run.id,
            "session_id": session.id,
            "session_title": session.title,
            "project_slug": project.slug,
            "project_name": project.name,
            "tool": tool,
            "arguments": args,
            "summary": summarize_tool_call(tool, args),
            "status": status,
            "started_at": start_event.created_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "duration_ms": duration_ms,
            "result_preview": _short(result, 500),
        })

    return {"activity": activity, "count": len(activity)}
