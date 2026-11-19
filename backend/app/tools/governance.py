"""Per-tool enable/disable and grant policy backed by SQLModel tables.

This module is the single source of truth used by both the API (Tools page) and
the run loop. Schema filtering is only defence-in-depth: execution is guarded
here too so a text-protocol tool call can never bypass a disabled tool.
"""
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from backend.app.db.models import ToolGrant, ToolSetting
from backend.app.tools.registry import get_tool_registry


GRANT_MODES = ("none", "prompt_once")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_tool_settings(db: Session) -> dict[str, ToolSetting]:
    """Return a setting row for every registered tool, creating missing rows."""
    known = {t.name: t for t in get_tool_registry().list_tools()}
    rows = {row.tool_name: row for row in db.exec(select(ToolSetting)).all()}
    created = False
    for name in known:
        if name not in rows:
            rows[name] = ToolSetting(tool_name=name, enabled=True, grant_mode="none")
            db.add(rows[name])
            created = True
    if created:
        db.commit()
        for row in rows.values():
            db.refresh(row)
    return rows


def enabled_tool_names(db: Session) -> list[str]:
    return [name for name, row in list_tool_settings(db).items() if row.enabled]


def is_enabled(db: Session, tool_name: str) -> bool:
    row = list_tool_settings(db).get(tool_name)
    return bool(row and row.enabled)


def grant_required(db: Session, tool_name: str) -> bool:
    row = list_tool_settings(db).get(tool_name)
    return bool(row and row.enabled and row.grant_mode == "prompt_once")


def has_grant(db: Session, run_id: str, tool_name: str) -> bool:
    now = _now()
    rows = db.exec(
        select(ToolGrant).where(
            ToolGrant.run_id == run_id,
            ToolGrant.tool_name == tool_name,
            ToolGrant.status == "granted",
        )
    ).all()
    for row in rows:
        if row.expires_at is None or row.expires_at > now:
            return True
    return False


def grant_tool(db: Session, run_id: str, tool_name: str, scope: str = "run") -> ToolGrant:
    """Record a user grant. Scope 'run' expires after 24h; 'once' is consumed."""
    row = ToolGrant(
        run_id=run_id,
        tool_name=tool_name,
        scope=scope,
        status="granted" if scope == "run" else "consumed",
        expires_at=_now() + timedelta(hours=24) if scope == "run" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_tool_setting(db: Session, tool_name: str, enabled: bool | None, grant_mode: str | None) -> ToolSetting:
    if get_tool_registry().get(tool_name) is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    if grant_mode is not None and grant_mode not in GRANT_MODES:
        raise ValueError(f"grant_mode must be one of {', '.join(GRANT_MODES)}")
    row = list_tool_settings(db)[tool_name]
    if enabled is not None:
        row.enabled = bool(enabled)
    if grant_mode is not None:
        row.grant_mode = grant_mode
    row.updated_at = _now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
