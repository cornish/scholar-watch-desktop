"""Database engine, session factory, and initialization."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import AppConfig, load_config
from .models import Base


_engine = None
_SessionFactory = None


def _set_sqlite_wal(dbapi_conn, connection_record):
    """Enable WAL mode for SQLite to allow concurrent reads."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_engine(config: AppConfig | None = None):
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        if config is None:
            config = load_config()
        _engine = create_engine(config.database.uri, echo=False)
        if config.database.uri.startswith("sqlite"):
            event.listen(_engine, "connect", _set_sqlite_wal)
    return _engine


def get_session(config: AppConfig | None = None) -> Session:
    """Create a new database session."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine(config)
        _SessionFactory = sessionmaker(bind=engine)
    return _SessionFactory()


def init_db(config: AppConfig | None = None) -> None:
    """Create all database tables."""
    engine = get_engine(config)
    Base.metadata.create_all(engine)


def reset_engine() -> None:
    """Reset cached engine and session factory (useful for testing)."""
    global _engine, _SessionFactory
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
