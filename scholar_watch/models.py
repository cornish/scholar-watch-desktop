"""SQLAlchemy ORM models for Scholar Watch."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Researcher(Base):
    __tablename__ = "researchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scholar_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    affiliation: Mapped[str | None] = mapped_column(String(500))
    interests: Mapped[str | None] = mapped_column(Text)  # JSON list stored as text
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime)

    publications: Mapped[list["Publication"]] = relationship(
        back_populates="researcher", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["ResearcherSnapshot"]] = relationship(
        back_populates="researcher", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Researcher(id={self.id}, scholar_id='{self.scholar_id}', name='{self.name}')>"


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("researcher_id", "title", name="uq_researcher_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    researcher_id: Mapped[int] = mapped_column(Integer, ForeignKey("researchers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(500))
    authors: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    researcher: Mapped["Researcher"] = relationship(back_populates="publications")
    citation_snapshots: Mapped[list["CitationSnapshot"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Publication(id={self.id}, title='{self.title[:50]}...')>"


class CitationSnapshot(Base):
    __tablename__ = "citation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[int] = mapped_column(Integer, ForeignKey("publications.id"), nullable=False, index=True)
    scrape_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("scrape_runs.id"), nullable=False, index=True)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    publication: Mapped["Publication"] = relationship(back_populates="citation_snapshots")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="citation_snapshots")


class ResearcherSnapshot(Base):
    __tablename__ = "researcher_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    researcher_id: Mapped[int] = mapped_column(Integer, ForeignKey("researchers.id"), nullable=False, index=True)
    scrape_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("scrape_runs.id"), nullable=False, index=True)
    h_index: Mapped[int | None] = mapped_column(Integer)
    i10_index: Mapped[int | None] = mapped_column(Integer)
    total_citations: Mapped[int | None] = mapped_column(Integer)
    cites_per_year: Mapped[dict | None] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    researcher: Mapped["Researcher"] = relationship(back_populates="snapshots")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="researcher_snapshots")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    researchers_scraped: Mapped[int] = mapped_column(Integer, default=0)
    publications_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    citation_snapshots: Mapped[list["CitationSnapshot"]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )
    researcher_snapshots: Mapped[list["ResearcherSnapshot"]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ScrapeRun(id={self.id}, status='{self.status}', started_at='{self.started_at}')>"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    researcher_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("researchers.id"))
    publication_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("publications.id"))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type='{self.notification_type}', read={self.is_read})>"
