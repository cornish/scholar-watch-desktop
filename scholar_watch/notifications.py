"""Notification generation after scrape runs."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from .models import (
    CitationSnapshot,
    Notification,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
)

logger = logging.getLogger(__name__)

CITATION_MILESTONES = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]


class NotificationGenerator:
    """Generates notifications by comparing pre/post scrape state."""

    def __init__(self, session: Session):
        self.session = session

    def generate_for_scrape_run(self, run: ScrapeRun) -> int:
        """Generate notifications for a completed scrape run.

        Returns the number of notifications created.
        """
        if run.status != "completed":
            return 0

        count = 0

        # Get all researcher snapshots from this run
        run_snapshots = (
            self.session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.scrape_run_id == run.id)
            .all()
        )

        for snapshot in run_snapshots:
            researcher = self.session.query(Researcher).get(snapshot.researcher_id)
            if not researcher:
                continue

            count += self._check_h_index_change(researcher, snapshot)
            count += self._check_citation_milestones(researcher, snapshot)
            count += self._check_new_publications(researcher, run)

        self.session.commit()
        logger.info("Generated %d notifications for scrape run %d", count, run.id)
        return count

    def _check_h_index_change(
        self, researcher: Researcher, current: ResearcherSnapshot
    ) -> int:
        """Check if h-index changed since the previous snapshot."""
        previous = (
            self.session.query(ResearcherSnapshot)
            .filter(
                ResearcherSnapshot.researcher_id == researcher.id,
                ResearcherSnapshot.id != current.id,
            )
            .order_by(ResearcherSnapshot.recorded_at.desc())
            .first()
        )

        if not previous or previous.h_index is None or current.h_index is None:
            return 0

        delta = current.h_index - previous.h_index
        if delta == 0:
            return 0

        direction = "increased" if delta > 0 else "decreased"
        notif = Notification(
            notification_type="h_index_change",
            title=f"h-index {direction} for {researcher.name}",
            message=f"h-index went from {previous.h_index} to {current.h_index} ({delta:+d})",
            researcher_id=researcher.id,
        )
        self.session.add(notif)
        return 1

    def _check_citation_milestones(
        self, researcher: Researcher, current: ResearcherSnapshot
    ) -> int:
        """Check if total citations crossed a milestone."""
        previous = (
            self.session.query(ResearcherSnapshot)
            .filter(
                ResearcherSnapshot.researcher_id == researcher.id,
                ResearcherSnapshot.id != current.id,
            )
            .order_by(ResearcherSnapshot.recorded_at.desc())
            .first()
        )

        if not previous or previous.total_citations is None or current.total_citations is None:
            return 0

        prev_cites = previous.total_citations
        curr_cites = current.total_citations

        crossed = [m for m in CITATION_MILESTONES if prev_cites < m <= curr_cites]
        if not crossed:
            return 0

        milestone = crossed[-1]  # Report the highest milestone crossed
        notif = Notification(
            notification_type="citation_milestone",
            title=f"{researcher.name} reached {milestone:,} citations!",
            message=f"Total citations: {curr_cites:,} (was {prev_cites:,})",
            researcher_id=researcher.id,
        )
        self.session.add(notif)
        return 1

    def _check_new_publications(
        self, researcher: Researcher, run: ScrapeRun
    ) -> int:
        """Check for publications first seen during this scrape run."""
        new_pubs = (
            self.session.query(Publication)
            .filter(
                Publication.researcher_id == researcher.id,
                Publication.first_seen_at >= run.started_at,
            )
            .all()
        )

        if not new_pubs:
            return 0

        titles = [p.title for p in new_pubs[:5]]
        extra = len(new_pubs) - 5 if len(new_pubs) > 5 else 0

        if len(new_pubs) == 1:
            title = f"New publication by {researcher.name}"
            message = new_pubs[0].title
        else:
            title = f"{len(new_pubs)} new publications by {researcher.name}"
            message = "\n".join(f"- {t}" for t in titles)
            if extra:
                message += f"\n... and {extra} more"

        notif = Notification(
            notification_type="new_publication",
            title=title,
            message=message,
            researcher_id=researcher.id,
        )
        self.session.add(notif)
        return 1
