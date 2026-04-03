"""Tests for database initialization and models."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import inspect

from scholar_watch.config import AppConfig, DatabaseConfig
from scholar_watch.database import get_engine, get_session, init_db, reset_engine
from scholar_watch.models import Base, Researcher, Publication


@pytest.fixture
def db_config(tmp_path):
    """Config with a temporary database."""
    reset_engine()
    db_path = tmp_path / "test.db"
    config = AppConfig(database=DatabaseConfig(path=str(db_path)))
    init_db(config)
    yield config
    reset_engine()


def test_init_db_creates_tables(db_config):
    engine = get_engine(db_config)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "researchers" in tables
    assert "publications" in tables
    assert "citation_snapshots" in tables
    assert "researcher_snapshots" in tables
    assert "scrape_runs" in tables
    assert "notifications" in tables


def test_add_researcher(db_config):
    session = get_session(db_config)
    try:
        r = Researcher(scholar_id="test123", name="Test User")
        session.add(r)
        session.commit()

        fetched = session.query(Researcher).filter_by(scholar_id="test123").first()
        assert fetched is not None
        assert fetched.name == "Test User"
        assert fetched.is_active is True
    finally:
        session.close()


def test_unique_publication(db_config):
    session = get_session(db_config)
    try:
        r = Researcher(scholar_id="test456", name="Researcher")
        session.add(r)
        session.commit()

        p1 = Publication(researcher_id=r.id, title="My Paper")
        session.add(p1)
        session.commit()

        p2 = Publication(researcher_id=r.id, title="My Paper")
        session.add(p2)
        with pytest.raises(Exception):
            session.commit()
    finally:
        session.close()
