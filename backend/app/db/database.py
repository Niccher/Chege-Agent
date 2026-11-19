from typing import Generator
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger

logger = get_logger("db")

_engine = None
_engine_url_key: str | None = None


def _resolve_db_url(settings: Settings) -> str:
    """Return the configured DSN, or the default embedded SQLite URL."""
    configured = (settings.database_url or "").strip()
    if configured:
        return configured
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{settings.data_dir / 'chege.db'}"


def get_engine():
    settings = get_settings()
    db_url = _resolve_db_url(settings)
    is_sqlite = db_url.startswith("sqlite:")

    kwargs: dict = {"echo": False}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Postgres: tolerate a brief DB restart and cap connections.
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)

    engine = create_engine(db_url, **kwargs)

    if is_sqlite:
        # WAL mode, foreign keys and synchronous NORMAL are SQLite-only.
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    logger.info(f"Database engine ready ({'sqlite' if is_sqlite else 'postgresql'}).")
    return engine


def get_db_engine():
    global _engine, _engine_url_key
    url_key = _resolve_db_url(get_settings())
    if _engine is None or _engine_url_key != url_key:
        _engine = get_engine()
        _engine_url_key = url_key
    return _engine


def _ensure_event_sequence_integrity(engine) -> None:
    """Renumber duplicate event sequences and add the uniqueness constraint.

    Older databases used a process-local counter, so seq values could repeat
    after a restart. SSE replay relies on (run_id, seq) being unique.
    """
    from sqlalchemy import text
    from backend.app.db.models import Event

    with Session(engine) as db:
        runs = db.exec(text("SELECT DISTINCT run_id FROM events")).all()
        for (run_id,) in runs:
            rows = db.exec(
                select(Event).where(Event.run_id == run_id).order_by(Event.created_at.asc(), Event.id.asc())
            ).all()
            for index, row in enumerate(rows, start=1):
                if row.seq != index:
                    row.seq = index
                    db.add(row)
        db.commit()

    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_events_run_seq ON events (run_id, seq)"))
        except Exception as exc:  # pragma: no cover - depends on DB backend
            logger.warning(f"Could not create event sequence index: {exc}")


def init_db() -> None:
    """Initialize database tables."""
    engine = get_db_engine()
    logger.info("Initializing database tables...")
    SQLModel.metadata.create_all(engine)
    _ensure_event_sequence_integrity(engine)
    logger.info("Database initialized successfully.")


def create_session(engine=None) -> Session:
    """Create a new Session with expire_on_commit=False."""
    eng = engine or get_db_engine()
    return Session(eng, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Dependency for yielding database sessions."""
    engine = get_db_engine()
    with Session(engine, expire_on_commit=False) as session:
        yield session
