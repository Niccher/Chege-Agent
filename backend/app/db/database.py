from pathlib import Path
from typing import Generator
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger("db")


def get_engine():
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = settings.data_dir / "chege.db"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable SQLite WAL mode and foreign key constraints on connect (DATA-01)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


_engine = None


def get_db_engine():
    global _engine
    settings = get_settings()
    expected_url = f"sqlite:///{settings.data_dir / 'chege.db'}"
    if _engine is None or str(_engine.url) != expected_url:
        _engine = get_engine()
    return _engine


def init_db() -> None:
    """Initialize database tables."""
    engine = get_db_engine()
    logger.info("Initializing database tables...")
    SQLModel.metadata.create_all(engine)
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

