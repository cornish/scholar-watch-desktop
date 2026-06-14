"""Tests for citing-paper capture (the data behind the 'which paper is the new cite' hover).

The live fetch happens via a real Chrome (Selenium) in ``browser_fetcher``; here we stub
``ScholarScraper._browser_fetch`` so the storage/dedup/cap/throttle logic is tested without
a browser or network. ``profile_is_setup`` is forced True by default so the fetch gate opens.
"""

from datetime import datetime, timedelta

import pytest

from scholar_watch import scraper as scraper_module
from scholar_watch.config import AppConfig, DatabaseConfig
from scholar_watch.database import get_session, init_db, reset_engine
from scholar_watch.models import (
    CitationSnapshot,
    CitingPaper,
    Notification,
    Publication,
    Researcher,
    ScrapeRun,
)
from scholar_watch.browser_fetcher import CitingCaptcha
from scholar_watch.scraper import (
    ScholarScraper,
    _extract_citing_bib,
    _normalize_title,
)


@pytest.fixture
def db_config(tmp_path):
    reset_engine()
    config = AppConfig(database=DatabaseConfig(path=str(tmp_path / "test.db")))
    # Keep tests fast: no real delay between (stubbed) fetches.
    config.scraping.min_delay = 0
    config.scraping.max_delay = 0
    config.scraping.citing_min_delay = 0
    config.scraping.citing_max_delay = 0
    init_db(config)
    yield config
    reset_engine()


@pytest.fixture(autouse=True)
def _profile_ready(monkeypatch):
    """Pretend the one-time Chrome login is done so the fetch gate is open."""
    monkeypatch.setattr(scraper_module, "profile_is_setup", lambda *_a, **_k: True)


def _norm(title, authors="A Author, B Writer", year=2025, venue="Nature", url="http://x"):
    """A normalized citing-paper dict — the shape _browser_fetch returns."""
    return {"title": title, "authors": authors, "year": year, "venue": venue, "url": url}


def _stub_browser(scraper, func):
    """Replace the real Selenium fetch with `func(url, limit)`."""
    scraper._browser_fetch = func


def _make_pub_with_history(session, count, title="My Paper"):
    """A researcher + publication with one prior citation snapshot at `count`."""
    r = Researcher(scholar_id="abc12345", name="R")
    session.add(r)
    session.flush()
    pub = Publication(researcher_id=r.id, title=title)
    session.add(pub)
    session.flush()
    run0 = ScrapeRun(started_at=datetime.utcnow() - timedelta(days=7), status="completed")
    session.add(run0)
    session.flush()
    session.add(CitationSnapshot(
        publication_id=pub.id, scrape_run_id=run0.id, citation_count=count,
        recorded_at=datetime.utcnow() - timedelta(days=7),
    ))
    session.commit()
    return r, pub


def test_normalize_title():
    assert _normalize_title("  Hello   World ") == "hello world"
    assert _normalize_title("Hello World") == _normalize_title("hello   world")


def test_extract_citing_bib_handles_author_list_and_string():
    a = _extract_citing_bib({"bib": {"title": "T", "author": ["X Y", "Z W"], "pub_year": "2024"}, "pub_url": "u"})
    assert a["authors"] == "X Y, Z W"
    assert a["year"] == 2024
    assert a["url"] == "u"
    b = _extract_citing_bib({"bib": {"title": "T", "author": "Single Author"}})
    assert b["authors"] == "Single Author"
    assert b["year"] is None
    assert _extract_citing_bib({"bib": {"title": "   "}}) is None  # no usable title


def test_new_cites_stored_and_capped_by_delta(db_config):
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)
        returned = [_norm("Citing One"), _norm("Citing Two"), _norm("Citing Three")]
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: returned[:limit])  # browser honors `limit`
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        # Count rose 5 -> 7 (delta 2): only the 2 newest should be stored.
        pub_data = {"bib": {"title": pub.title}, "num_citations": 7, "citedby_url": "/scholar?cites=1"}
        scraper._process_publication(r, pub_data, run)
        session.commit()

        cites = session.query(CitingPaper).filter_by(publication_id=pub.id).all()
        assert len(cites) == 2
        assert {c.title for c in cites} == {"Citing One", "Citing Two"}
        assert all(c.first_seen_run_id == run.id for c in cites)
    finally:
        session.close()


def test_absolute_citedby_url_normalized_to_path(db_config):
    """A full-URL citedby_url must be reduced to a path, else the host gets doubled."""
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)
        seen = {}

        def fake(url, limit):
            seen["url"] = url
            return [_norm("C1")]
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, fake)
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        pub_data = {
            "bib": {"title": pub.title},
            "num_citations": 6,
            # Absolute URL, as Google Scholar profile pages sometimes return.
            "citedby_url": "https://scholar.google.com/scholar?oi=bibs&hl=en&cites=12345",
        }
        scraper._process_publication(r, pub_data, run)
        session.commit()

        url = seen["url"]
        assert url.startswith("/scholar?"), url           # a path, not a full URL
        assert "scholar.google.com" not in url            # host must not be embedded
        assert "scisbd=1" in url and "cites=12345" in url  # newest-first + original query kept
    finally:
        session.close()


def test_dedup_across_runs(db_config):
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)
        scraper = ScholarScraper(db_config, session)
        # Same paper twice with messy text -> normalizes to one key.
        _stub_browser(scraper, lambda url, limit: [_norm("Citing One"), _norm("  citing   one ")][:limit])
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        pub_data = {"bib": {"title": pub.title}, "num_citations": 7, "citedby_url": "/scholar?cites=1"}
        scraper._process_publication(r, pub_data, run)
        session.commit()

        assert session.query(CitingPaper).filter_by(publication_id=pub.id).count() == 1
    finally:
        session.close()


def test_brand_new_publication_skips_fetch(db_config):
    session = get_session(db_config)
    try:
        r = Researcher(scholar_id="def67890", name="R2")
        session.add(r)
        session.commit()

        calls = []
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: calls.append(url) or [_norm("Should Not Store")])
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        # First time we ever see this paper: no prior baseline, so no cited-by fetch.
        pub_data = {"bib": {"title": "Fresh Paper"}, "num_citations": 10, "citedby_url": "/scholar?cites=9"}
        scraper._process_publication(r, pub_data, run)
        session.commit()

        assert calls == []
        assert session.query(CitingPaper).count() == 0
    finally:
        session.close()


def _make_pubs(session, n, count=5):
    """One researcher with n publications, each carrying a prior snapshot at `count`."""
    r = Researcher(scholar_id="cap00000", name="R")
    session.add(r)
    session.flush()
    run0 = ScrapeRun(started_at=datetime.utcnow() - timedelta(days=7), status="completed")
    session.add(run0)
    session.flush()
    pubs = []
    for i in range(n):
        p = Publication(researcher_id=r.id, title=f"Paper {i}")
        session.add(p)
        session.flush()
        session.add(CitationSnapshot(
            publication_id=p.id, scrape_run_id=run0.id, citation_count=count,
            recorded_at=datetime.utcnow() - timedelta(days=7),
        ))
        pubs.append(p)
    session.commit()
    return r, pubs


def test_per_run_cap_defers_extra_papers(db_config):
    session = get_session(db_config)
    try:
        r, pubs = _make_pubs(session, n=4)
        db_config.scraping.max_citing_pubs_per_run = 2
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: [_norm("Cite")][:limit])
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        for p in pubs:
            pub_data = {"bib": {"title": p.title}, "num_citations": 6, "citedby_url": "/scholar?cites=1"}
            scraper._process_publication(r, pub_data, run)
        session.commit()

        assert scraper._citing_attempts == 2
        assert scraper._citing_skipped_cap == 2
        scraper._emit_citing_warnings(run)
        session.commit()
        notif = session.query(Notification).filter_by(notification_type="citing_deferred").first()
        assert notif is not None and "2" in notif.title
    finally:
        session.close()


def test_throttle_detection_stops_and_warns(db_config):
    session = get_session(db_config)
    try:
        r, pubs = _make_pubs(session, n=5)

        def boom(url, limit):
            raise RuntimeError("Cannot Fetch from Google Scholar.")
        db_config.scraping.citing_throttle_threshold = 2
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, boom)
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        for p in pubs:
            pub_data = {"bib": {"title": p.title}, "num_citations": 6, "citedby_url": "/scholar?cites=1"}
            scraper._process_publication(r, pub_data, run)

        # Throttle trips after 2 failures; remaining papers are skipped (no more attempts).
        assert scraper._throttle_detected is True
        assert scraper._citing_attempts == 2
        scraper._emit_citing_warnings(run)
        session.commit()
        notif = session.query(Notification).filter_by(notification_type="citing_throttled").first()
        assert notif is not None
    finally:
        session.close()


def test_empty_results_trip_throttle(db_config):
    """Empty cited-by pages (Google's soft block) count toward the throttle stop."""
    session = get_session(db_config)
    try:
        r, pubs = _make_pubs(session, n=5)
        db_config.scraping.citing_throttle_threshold = 2
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: [])   # soft block: page with no results
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        for p in pubs:
            pub_data = {"bib": {"title": p.title}, "num_citations": 6, "citedby_url": "/scholar?cites=1"}
            scraper._process_publication(r, pub_data, run)

        assert scraper._throttle_detected is True
        assert scraper._citing_attempts == 2
        assert session.query(CitingPaper).count() == 0
    finally:
        session.close()


def test_failed_fetch_is_retried_at_end_of_run(db_config):
    """A cited-by fetch that fails once (e.g. a CAPTCHA) is replayed at the end of the
    run, so the paper isn't left with a '+N' badge but an empty 'who cited this' list."""
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)

        # Fail the first attempt (as if blocked), succeed on the retry.
        state = {"first": True}

        def flaky(url, limit):
            if state["first"]:
                state["first"] = False
                raise CitingCaptcha(url)
            return [_norm("Recovered Cite")][:limit]

        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, flaky)
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        pub_data = {"bib": {"title": pub.title}, "num_citations": 6, "citedby_url": "/scholar?cites=1"}
        scraper._process_publication(r, pub_data, run)

        # First pass failed and nothing stored yet, but it's queued for retry.
        assert session.query(CitingPaper).count() == 0
        assert len(scraper._citing_retry_queue) == 1

        # End-of-run retry pass recovers it, attached to the same run.
        scraper._run_citing_retries(run)
        session.commit()
        stored = session.query(CitingPaper).all()
        assert [c.title for c in stored] == ["Recovered Cite"]
        assert stored[0].first_seen_run_id == run.id
        assert scraper._citing_retry_queue == []     # queue drained, no infinite loop
    finally:
        session.close()


def test_unconnected_browser_skips_and_prompts_setup(db_config, monkeypatch):
    """If Chrome isn't connected, fetching is skipped and a setup notification is posted."""
    monkeypatch.setattr(scraper_module, "profile_is_setup", lambda *_a, **_k: False)
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)
        calls = []
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: calls.append(url) or [_norm("X")])
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        pub_data = {"bib": {"title": pub.title}, "num_citations": 8, "citedby_url": "/scholar?cites=1"}
        scraper._process_publication(r, pub_data, run)
        assert calls == []                       # never tried to fetch
        assert scraper._browser_setup_needed is True
        scraper._emit_citing_warnings(run)
        session.commit()
        assert session.query(Notification).filter_by(notification_type="citing_setup").first() is not None
    finally:
        session.close()


def test_captcha_flips_browser_visible_then_succeeds(db_config, monkeypatch):
    """A headless CAPTCHA reopens Chrome visibly once and retries."""

    class FakeFetcher:
        def __init__(self, profile_dir, headless=True):
            self.headless = headless

        def fetch(self, url, limit, solve_timeout=0):
            if self.headless:
                raise CitingCaptcha(url)        # blocked while hidden
            return [_norm("Solved Cite")][:limit]  # works once visible/solved

        def restart(self, headless):
            self.headless = headless

        def surface_window(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(scraper_module, "BrowserCitingFetcher", FakeFetcher)
    session = get_session(db_config)
    try:
        db_config.scraping.citing_browser_headless = True   # start hidden so the flip is exercised
        scraper = ScholarScraper(db_config, session)
        out = scraper._browser_fetch("/scholar?cites=1&scisbd=1", 5)
        assert [o["title"] for o in out] == ["Solved Cite"]
        assert scraper._browser.headless is False     # flipped to visible
        assert scraper._tried_captcha_solve is True
    finally:
        session.close()


def test_disabled_setting_skips_fetch(db_config):
    session = get_session(db_config)
    try:
        r, pub = _make_pub_with_history(session, count=5)
        calls = []
        db_config.scraping.fetch_citing_papers = False
        scraper = ScholarScraper(db_config, session)
        _stub_browser(scraper, lambda url, limit: calls.append(url) or [_norm("X")])
        run = ScrapeRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()

        pub_data = {"bib": {"title": pub.title}, "num_citations": 9, "citedby_url": "/scholar?cites=1"}
        scraper._process_publication(r, pub_data, run)
        session.commit()

        assert calls == []
        assert session.query(CitingPaper).count() == 0
    finally:
        session.close()
