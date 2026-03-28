"""Scholarly wrapper for scraping Google Scholar profiles."""

import json
import logging
import random
import time
from datetime import datetime

from scholarly import scholarly, ProxyGenerator
from sqlalchemy.orm import Session

from .config import AppConfig, ScrapingConfig
from .models import (
    CitationSnapshot,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
)
from .notifications import NotificationGenerator

logger = logging.getLogger(__name__)


class ScholarScraper:
    """Scrapes Google Scholar profiles and stores snapshot data."""

    def __init__(self, config: AppConfig, session: Session):
        self.config = config
        self.scraping = config.scraping
        self.session = session
        self._setup_proxy()

    def _setup_proxy(self) -> None:
        """Configure scholarly proxy if specified."""
        proxy_cfg = self.scraping.proxy
        if proxy_cfg.type == "none":
            return

        pg = ProxyGenerator()
        if proxy_cfg.type == "free":
            pg.FreeProxies()
        elif proxy_cfg.type == "tor":
            pg.Tor_Internal()
        elif proxy_cfg.type == "scraperapi":
            pg.ScraperAPI(proxy_cfg.api_key)
        elif proxy_cfg.type == "single":
            pg.SingleProxy(http=proxy_cfg.http, https=proxy_cfg.https)
        else:
            logger.warning("Unknown proxy type '%s', using no proxy", proxy_cfg.type)
            return

        scholarly.use_proxy(pg)
        logger.info("Configured proxy: %s", proxy_cfg.type)

    def _delay(self) -> None:
        """Random delay between API calls to be respectful."""
        delay = random.uniform(self.scraping.min_delay, self.scraping.max_delay)
        logger.debug("Waiting %.1f seconds before next request", delay)
        time.sleep(delay)

    def scrape_all(self) -> ScrapeRun:
        """Scrape all active researchers."""
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        self.session.add(run)
        self.session.commit()

        researchers = (
            self.session.query(Researcher)
            .filter(Researcher.is_active.is_(True))
            .all()
        )

        if not researchers:
            logger.warning("No active researchers to scrape")
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            self.session.commit()
            return run

        try:
            for researcher in researchers:
                self._scrape_researcher(researcher, run)
                run.researchers_scraped += 1
                self.session.commit()

            run.status = "completed"
        except Exception as e:
            logger.error("Scrape run failed: %s", e)
            run.status = "failed"
            run.error_message = str(e)
        finally:
            run.completed_at = datetime.utcnow()
            self.session.commit()

        logger.info(
            "Scrape run %d: %s (%d researchers, %d publications)",
            run.id, run.status, run.researchers_scraped, run.publications_found,
        )

        if run.status == "completed":
            try:
                NotificationGenerator(self.session).generate_for_scrape_run(run)
            except Exception as e:
                logger.error("Notification generation failed: %s", e)

        return run

    def scrape_one(self, scholar_id: str) -> ScrapeRun:
        """Scrape a single researcher by Scholar ID."""
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        self.session.add(run)
        self.session.commit()

        researcher = (
            self.session.query(Researcher)
            .filter(Researcher.scholar_id == scholar_id)
            .first()
        )

        if not researcher:
            run.status = "failed"
            run.error_message = f"Researcher '{scholar_id}' not found in database"
            run.completed_at = datetime.utcnow()
            self.session.commit()
            return run

        try:
            self._scrape_researcher(researcher, run)
            run.researchers_scraped = 1
            run.status = "completed"
        except Exception as e:
            logger.error("Scrape failed for %s: %s", scholar_id, e)
            run.status = "failed"
            run.error_message = str(e)
        finally:
            run.completed_at = datetime.utcnow()
            self.session.commit()

        return run

    def _scrape_researcher(self, researcher: Researcher, run: ScrapeRun) -> None:
        """Scrape a single researcher's profile and publications."""
        logger.info("Scraping researcher: %s (%s)", researcher.name, researcher.scholar_id)

        self._delay()

        # Fetch author profile with publications in one call
        author = scholarly.search_author_id(researcher.scholar_id)
        author = scholarly.fill(author, sections=["basics", "indices", "publications"])

        # Update researcher metadata
        researcher.name = author.get("name", researcher.name)
        researcher.affiliation = author.get("affiliation", "")
        interests = author.get("interests", [])
        researcher.interests = json.dumps(interests) if interests else None
        researcher.last_scraped_at = datetime.utcnow()

        # Create researcher snapshot
        citedby = author.get("citedby", 0) or 0
        h_index = author.get("hindex", 0) or 0
        i10_index = author.get("i10index", 0) or 0
        cites_per_year = author.get("cites_per_year", {})

        r_snapshot = ResearcherSnapshot(
            researcher_id=researcher.id,
            scrape_run_id=run.id,
            h_index=h_index,
            i10_index=i10_index,
            total_citations=citedby,
            cites_per_year=cites_per_year,
            recorded_at=datetime.utcnow(),
        )
        self.session.add(r_snapshot)

        # Process publications
        publications = author.get("publications", [])
        max_pubs = self.scraping.max_publications
        for pub_data in publications[:max_pubs]:
            self._process_publication(researcher, pub_data, run)

        run.publications_found += min(len(publications), max_pubs)
        logger.info(
            "  -> %s: %d publications, h-index=%d, citations=%d",
            researcher.name, min(len(publications), max_pubs), h_index, citedby,
        )

    def _process_publication(
        self, researcher: Researcher, pub_data: dict, run: ScrapeRun
    ) -> None:
        """Process a single publication from scholarly data."""
        bib = pub_data.get("bib", {})
        title = bib.get("title", "").strip()
        if not title:
            return

        # Find or create publication
        pub = (
            self.session.query(Publication)
            .filter(
                Publication.researcher_id == researcher.id,
                Publication.title == title,
            )
            .first()
        )

        now = datetime.utcnow()
        if pub is None:
            pub = Publication(
                researcher_id=researcher.id,
                title=title,
                year=bib.get("pub_year") or bib.get("year"),
                venue=bib.get("venue", "") or bib.get("journal", "") or bib.get("conference", ""),
                authors=bib.get("author", ""),
                url=pub_data.get("pub_url", ""),
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(pub)
            self.session.flush()  # Get the ID
        else:
            pub.last_seen_at = now
            # Update metadata if it was missing
            if not pub.year:
                pub.year = bib.get("pub_year") or bib.get("year")
            if not pub.venue:
                pub.venue = bib.get("venue", "") or bib.get("journal", "") or bib.get("conference", "")

        # Create citation snapshot
        num_citations = pub_data.get("num_citations", 0) or 0
        snapshot = CitationSnapshot(
            publication_id=pub.id,
            scrape_run_id=run.id,
            citation_count=num_citations,
            recorded_at=now,
        )
        self.session.add(snapshot)
