"""Scholarly wrapper for scraping Google Scholar profiles."""

import json
import logging
import random
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

from scholarly import scholarly, ProxyGenerator
from sqlalchemy.orm import Session

from .browser_fetcher import (
    BrowserCitingFetcher,
    CitingCaptcha,
    profile_is_setup,
    resolve_profile_dir,
)
from .config import AppConfig, ScrapingConfig
from .models import (
    CitationSnapshot,
    CitingPaper,
    Notification,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
)
from .notifications import NotificationGenerator
from .settings_store import CITING_ENABLED, get_bool

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """Normalize a title into a dedup key: lowercase, collapse whitespace, strip."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _extract_citing_bib(pub: dict) -> dict | None:
    """Pull display fields out of a scholarly search-result publication.

    Returns a dict with title/authors/year/venue/url, or None if there's no title.
    Scholar results vary, so every field is read defensively.
    """
    bib = pub.get("bib", {}) or {}
    title = (bib.get("title") or "").strip()
    if not title:
        return None

    author = bib.get("author")
    if isinstance(author, list):
        authors = ", ".join(a for a in author if a)
    else:
        authors = (author or "").strip()

    year = bib.get("pub_year") or bib.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    venue = (bib.get("venue") or bib.get("journal") or bib.get("conference") or "").strip()

    return {
        "title": title,
        "authors": authors or None,
        "year": year,
        "venue": venue or None,
        "url": (pub.get("pub_url") or "").strip() or None,
    }


class ScholarScraper:
    """Scrapes Google Scholar profiles and stores snapshot data."""

    def __init__(self, config: AppConfig, session: Session, status_callback=None):
        self.config = config
        self.scraping = config.scraping
        self.session = session
        # Optional one-arg callable(message: str) for surfacing live progress to the
        # UI (e.g. "solve the CAPTCHA in the Chrome window"). Best-effort; never fatal.
        self._status_callback = status_callback
        self._reset_citing_state()
        self._setup_proxy()

    def _reset_citing_state(self) -> None:
        """Per-run bookkeeping for the 'who cited this' fetches."""
        self._citing_attempts = 0          # papers we made a Cited-by request for
        self._citing_skipped_cap = 0       # papers deferred because the per-run cap was hit
        self._consec_citing_failures = 0   # consecutive Scholar refusals (throttle signal)
        self._throttle_detected = False     # once true, we stop fetching for the rest of the run
        self._browser = None                # lazily-started Selenium Chrome (one per run)
        self._tried_captcha_solve = False   # only do the interactive CAPTCHA-solve flow once per run
        self._captcha_seen = False          # surfaced Chrome for a CAPTCHA at some point this run
        self._browser_setup_needed = False  # true if we skipped because Chrome isn't connected
        # (pub, citedby_url, delta) for fetches that failed mid-run; retried once at the
        # end of the run after the user has had a chance to clear a block (see fix below).
        self._citing_retry_queue = []
        # Effective on/off: DB setting wins, else the config default.
        self._citing_enabled = get_bool(self.session, CITING_ENABLED, self.scraping.fetch_citing_papers)
        self._citing_profile_dir = resolve_profile_dir(self.scraping.citing_browser_profile_dir)

    def _close_browser(self) -> None:
        if self._browser is not None:
            self._browser.stop()
            self._browser = None

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

    def _citing_delay(self) -> None:
        """Longer random delay before a 'Cited by' browser fetch.

        These deep-link listing pages are the requests Google guards most, so we space
        them out more than ordinary profile fetches to keep CAPTCHAs rare.
        """
        delay = random.uniform(self.scraping.citing_min_delay, self.scraping.citing_max_delay)
        logger.debug("Waiting %.1f seconds before next cited-by fetch", delay)
        time.sleep(delay)

    def _status(self, message: str) -> None:
        """Best-effort live progress message to the UI (never raises)."""
        if not self._status_callback:
            return
        try:
            self._status_callback(message)
        except Exception as e:
            logger.debug("Status callback failed: %s", e)

    def scrape_all(self) -> ScrapeRun:
        """Scrape all active researchers."""
        self._reset_citing_state()
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
            try:
                self._run_citing_retries(run)
            except Exception as e:
                logger.warning("Cited-by retry pass failed: %s", e)
            self._close_browser()
            run.completed_at = datetime.utcnow()
            self._emit_citing_warnings(run)
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
        self._reset_citing_state()
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
            try:
                self._run_citing_retries(run)
            except Exception as e:
                logger.warning("Cited-by retry pass failed: %s", e)
            self._close_browser()
            run.completed_at = datetime.utcnow()
            self._emit_citing_warnings(run)
            self.session.commit()

        return run

    def _emit_citing_warnings(self, run: ScrapeRun) -> None:
        """Surface a notification if citing-paper fetches were throttled or deferred.

        Uses the app's existing Notification panel so users who don't scrape on a
        regular cadence find out *why* some "who cited this" details are missing.
        """
        try:
            if self._browser_setup_needed:
                self.session.add(Notification(
                    notification_type="citing_setup",
                    title="Connect Chrome to see who cited your papers",
                    message=(
                        "Some papers gained citations, but the 'who cited this' details "
                        "need a one-time Chrome sign-in. Open the home page and click "
                        "\"Connect browser\", sign into Google, then close that window."
                    ),
                ))
            elif self._throttle_detected:
                self.session.add(Notification(
                    notification_type="citing_throttled",
                    title="Google Scholar limited our requests",
                    message=(
                        "Scholar started refusing requests, so 'who cited this' details "
                        "were skipped for the rest of this run to avoid being blocked. "
                        "Citation counts are still up to date; the missing details fill "
                        "in automatically over your next few runs."
                    ),
                ))
            elif self._citing_skipped_cap > 0:
                self.session.add(Notification(
                    notification_type="citing_deferred",
                    title=f"Citing-paper details deferred for {self._citing_skipped_cap} paper(s)",
                    message=(
                        f"To stay light on Google Scholar, 'who cited this' details for "
                        f"{self._citing_skipped_cap} paper(s) were deferred to a future run. "
                        "This is normal after a long gap between scrapes."
                    ),
                ))
        except Exception as e:
            logger.warning("Could not record citing-paper notification: %s", e)

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
        citedby_url = pub_data.get("citedby_url") or None
        prev_count: int | None = None
        if pub is None:
            pub = Publication(
                researcher_id=researcher.id,
                title=title,
                year=bib.get("pub_year") or bib.get("year"),
                venue=bib.get("venue", "") or bib.get("journal", "") or bib.get("conference", ""),
                authors=bib.get("author", ""),
                url=pub_data.get("pub_url", ""),
                citedby_url=citedby_url,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(pub)
            self.session.flush()  # Get the ID
        else:
            pub.last_seen_at = now
            if citedby_url:
                pub.citedby_url = citedby_url  # keep the "Cited by" link fresh
            # Update metadata if it was missing
            if not pub.year:
                pub.year = bib.get("pub_year") or bib.get("year")
            if not pub.venue:
                pub.venue = bib.get("venue", "") or bib.get("journal", "") or bib.get("conference", "")
            # Most recent prior citation count (used to decide if new cites appeared)
            prev = (
                self.session.query(CitationSnapshot)
                .filter(CitationSnapshot.publication_id == pub.id)
                .order_by(CitationSnapshot.recorded_at.desc())
                .first()
            )
            prev_count = prev.citation_count if prev else None

        # Create citation snapshot
        num_citations = pub_data.get("num_citations", 0) or 0
        snapshot = CitationSnapshot(
            publication_id=pub.id,
            scrape_run_id=run.id,
            citation_count=num_citations,
            recorded_at=now,
        )
        self.session.add(snapshot)

        # If the count rose, capture *which* papers are the new cites (going forward only:
        # we skip brand-new publications, which have no prior baseline to diff against).
        if (
            self._citing_enabled
            and prev_count is not None
            and num_citations > prev_count
        ):
            if self._throttle_detected:
                # Scholar is refusing us; don't keep hammering for the rest of the run.
                return
            if not profile_is_setup(self._citing_profile_dir):
                # Chrome hasn't been connected yet — can't fetch; prompt setup once.
                self._browser_setup_needed = True
                return
            cap = self.scraping.max_citing_pubs_per_run
            if cap and self._citing_attempts >= cap:
                # Per-run budget spent; defer this paper's detail to a future run.
                self._citing_skipped_cap += 1
                return
            self._fetch_citing_papers(
                pub, pub_data.get("citedby_url"), num_citations - prev_count, run
            )

    def _fetch_citing_papers(
        self,
        pub: Publication,
        citedby_url: str | None,
        delta: int,
        run: ScrapeRun,
        is_retry: bool = False,
    ) -> None:
        """Fetch the newest citing papers for a publication and store the new ones.

        Frugal by design: we sort Google Scholar's "Cited by" list newest-first
        (``scisbd=1``) and take only the top ``delta`` results (capped), so a typical
        weekly +1..+10 costs a single extra request. New-indexed order is the best
        available proxy for "the citation that incremented the count"; dedup by
        normalized title keeps it self-correcting across runs.

        On failure (CAPTCHA, soft block, error) the fetch is queued for one retry at the
        end of the run (unless this *is* the retry), so a block the user clears partway
        through doesn't leave a paper with a "+N" badge but an empty "who cited this".
        """
        if not citedby_url:
            return

        # scholarly's iterator prepends the host, so it needs a *path* (not a full URL).
        # Profile "Cited by" links sometimes come back absolute, which would otherwise
        # produce a doubled host (scholar.google.com + https://scholar.google.com/...).
        parts = urlsplit(citedby_url)
        path = parts.path
        if not path:
            return
        url = f"{path}?{parts.query}" if parts.query else path
        url += ("&" if "?" in url else "?") + "scisbd=1"  # sort cited-by by date, newest first

        limit = min(delta, self.scraping.max_citing_per_pub)

        if not is_retry:
            self._citing_attempts += 1
        try:
            self._citing_delay()
            bibs = self._browser_fetch(url, limit)
            if not bibs:
                # delta > 0 means the paper *has* recent cites, so an empty page is a
                # soft block (Google returns a results-less page instead of a CAPTCHA).
                self._register_citing_failure(pub, "empty results (soft block)")
                self._queue_citing_retry(pub, citedby_url, delta, is_retry)
                return
            added = 0
            for bib in bibs:
                norm_key = _normalize_title(bib["title"])
                exists = (
                    self.session.query(CitingPaper.id)
                    .filter(
                        CitingPaper.publication_id == pub.id,
                        CitingPaper.norm_key == norm_key,
                    )
                    .first()
                )
                if exists:
                    continue
                self.session.add(
                    CitingPaper(
                        publication_id=pub.id,
                        first_seen_run_id=run.id,
                        title=bib["title"][:1000],
                        authors=bib["authors"],
                        year=bib["year"],
                        venue=(bib["venue"][:500] if bib["venue"] else None),
                        url=(bib["url"][:1000] if bib["url"] else None),
                        norm_key=norm_key[:255],
                    )
                )
                added += 1
            self._consec_citing_failures = 0  # a clean fetch clears the throttle streak
            logger.info(
                "    citing papers: +%d cite(s) on '%s', stored %d new",
                delta, pub.title[:60], added,
            )
        except Exception as e:
            kind = "CAPTCHA" if isinstance(e, CitingCaptcha) else "error"
            self._register_citing_failure(pub, kind)
            self._queue_citing_retry(pub, citedby_url, delta, is_retry)
            logger.warning(
                "Could not fetch citing papers for '%s' (%s): %s", pub.title[:60], kind, e
            )

    def _queue_citing_retry(
        self, pub: Publication, citedby_url: str, delta: int, is_retry: bool
    ) -> None:
        """Remember a failed cited-by fetch so it can be retried once at the end of the run."""
        if is_retry:
            return  # already the second attempt; don't loop
        self._citing_retry_queue.append((pub, citedby_url, delta))

    def _run_citing_retries(self, run: ScrapeRun) -> None:
        """Second-chance pass for cited-by fetches that failed earlier this run.

        A CAPTCHA early in a run can fail a few fetches before the user solves it; once
        the session is unblocked the rest of the run succeeds, so we replay the failed
        fetches a single time, attached to the same run, so their "+N" badges get a
        populated "who cited this" list instead of an empty popover.
        """
        if not self._citing_retry_queue:
            return
        queue, self._citing_retry_queue = self._citing_retry_queue, []
        # The earlier failures may have tripped the throttle stop; the user has since had
        # a chance to clear the block (e.g. solved a CAPTCHA), so give the retries a
        # clean slate. If they fail again, the throttle simply re-trips.
        self._throttle_detected = False
        self._consec_citing_failures = 0
        logger.info("Retrying %d cited-by fetch(es) that failed earlier this run", len(queue))
        for pub, citedby_url, delta in queue:
            if self._throttle_detected:
                break
            self._fetch_citing_papers(pub, citedby_url, delta, run, is_retry=True)

    def _register_citing_failure(self, pub: Publication, reason: str) -> None:
        """Count a failed/blocked cited-by fetch; trip the throttle stop at the threshold."""
        self._consec_citing_failures += 1
        if self._consec_citing_failures >= self.scraping.citing_throttle_threshold:
            self._throttle_detected = True
            logger.warning(
                "Google Scholar appears to be blocking us (%d cited-by fetches failed in a "
                "row, last: %s); skipping citing-paper fetches for the rest of this run.",
                self._consec_citing_failures, reason,
            )

    def _browser_fetch(self, url_path: str, limit: int) -> list[dict]:
        """Fetch via the real-Chrome driver, surfacing the window on a CAPTCHA.

        Chrome runs minimized (or headless) to stay out of the way, but a CAPTCHA needs
        a human — so on the first one this run we make the window visible, bring it to
        the front, tell the user, and wait for them to solve it. The solved session
        persists in the profile so the rest of the run sails through. A CAPTCHA we still
        can't get past propagates to the throttle path.
        """
        if self._browser is None:
            self._browser = BrowserCitingFetcher(
                self._citing_profile_dir, headless=self.scraping.citing_browser_headless
            )
        try:
            return self._browser.fetch(url_path, limit)
        except CitingCaptcha:
            if self._tried_captcha_solve:
                raise
            self._tried_captcha_solve = True
            self._captcha_seen = True
            logger.warning("CAPTCHA hit — bringing Chrome to the front so you can solve it...")
            if self._browser.headless:
                # No window to show in headless mode; relaunch visible first.
                self._browser.restart(headless=False)
            self._browser.surface_window()
            self._status(
                "Action needed: a Google Scholar CAPTCHA opened in the Chrome window — "
                "please solve it so the scrape can continue."
            )
            return self._browser.fetch(
                url_path, limit, solve_timeout=self.scraping.citing_captcha_solve_timeout
            )
