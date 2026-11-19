import json
from pathlib import Path
from sqlmodel import Session, select
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.database import get_db_engine, init_db
from backend.app.db.models import Message, Project, Session as DBSession

logger = get_logger("migration")


def migrate_legacy_logs():
    """Migrate legacy logs/*/chat_history.json and project_brain.json into SQLite (DATA-02)."""
    settings = get_settings()
    init_db()
    engine = get_db_engine()

    logs_dir = settings.logs_dir
    if not logs_dir.exists():
        logger.info(f"Logs directory {logs_dir} not found. Skipping migration.")
        return

    logger.info("Starting legacy data migration from logs/...")

    with Session(engine) as db:
        for project_dir in logs_dir.iterdir():
            if not project_dir.is_dir():
                continue

            slug = project_dir.name
            logger.info(f"Processing project directory: {slug}")

            # Check if project already exists
            existing_project = db.exec(select(Project).where(Project.slug == slug)).first()
            if not existing_project:
                project = Project(
                    name=slug.replace("-", " ").title(),
                    slug=slug,
                )

                # Check project brain
                brain_file = project_dir / "project_brain.json"
                if brain_file.exists():
                    try:
                        brain_data = json.loads(brain_file.read_text(encoding="utf-8"))
                        project.brain_goal = brain_data.get("goal", "")
                        project.brain_stack = brain_data.get("stack", "")
                        project.brain_notes = brain_data.get("notes", "")
                    except Exception as e:
                        logger.warning(f"Could not parse {brain_file}: {e}")

                db.add(project)
                db.commit()
                db.refresh(project)
            else:
                project = existing_project

            # Check for chat history
            history_file = project_dir / "chat_history.json"
            if history_file.exists():
                try:
                    history = json.loads(history_file.read_text(encoding="utf-8"))
                    if isinstance(history, list) and history:
                        # Check if session already created
                        existing_session = db.exec(
                            select(DBSession).where(DBSession.project_id == project.id)
                        ).first()

                        if not existing_session:
                            session_record = DBSession(
                                project_id=project.id,
                                title="Imported Session (v1)",
                            )
                            db.add(session_record)
                            db.commit()
                            db.refresh(session_record)

                            message_count = 0
                            for item in history:
                                if not isinstance(item, dict):
                                    continue
                                role = item.get("role", "user")
                                content = item.get("content", "")
                                tool_calls = item.get("tool_calls")
                                tool_calls_json = json.dumps(tool_calls) if tool_calls else None

                                msg = Message(
                                    session_id=session_record.id,
                                    role=role,
                                    content=content or "",
                                    tool_calls_json=tool_calls_json,
                                )
                                db.add(msg)
                                message_count += 1

                            db.commit()
                            logger.info(
                                f"Migrated {message_count} messages for project '{slug}' into session '{session_record.id}'."
                            )
                except Exception as e:
                    logger.error(f"Error migrating history for {slug}: {e}")

    logger.info("Legacy migration complete.")


if __name__ == "__main__":
    migrate_legacy_logs()
