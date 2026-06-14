"""Database engine, session factory, and initialization."""

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import AppConfig, load_config
from .models import Base

logger = logging.getLogger(__name__)


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


def _ensure_columns(engine) -> None:
    """Add columns that exist on the models but not yet in the DB.

    ``create_all`` adds missing tables but never alters existing ones, and the frozen
    desktop app has no Alembic runner — so we additively patch in new nullable columns
    here to keep existing databases in sync after upgrades.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.tables.values():
        if table.name not in existing_tables:
            continue  # create_all already made it
        have = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have or not column.nullable:
                continue  # present, or a non-nullable column we can't safely add post-hoc
            ddl_type = column.type.compile(engine.dialect)
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}'))
                logger.info("Added missing column %s.%s", table.name, column.name)
            except Exception as e:
                logger.warning("Could not add column %s.%s: %s", table.name, column.name, e)


def init_db(config: AppConfig | None = None) -> None:
    """Create all database tables (and patch in any newly-added columns)."""
    engine = get_engine(config)
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


def reset_engine() -> None:
    """Reset cached engine and session factory (useful for testing)."""
    global _engine, _SessionFactory
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
