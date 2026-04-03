"""Eel-exposed API functions for the desktop app."""

import json
import logging
import re
import threading

import eel

from ..config import AppConfig
from ..database import get_session
from ..metrics import MetricsCalculator
from .. import charts
from ..models import (
    CitationSnapshot,
    Notification,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
)

logger = logging.getLogger(__name__)

_config: AppConfig | None = None
_scrape_lock = threading.Lock()
_scrape_running = False


def set_config(config: AppConfig) -> None:
    global _config
    _config = config


def _get_session():
    return get_session(_config)


def _extract_scholar_id(raw: str) -> str:
    """Extract a Google Scholar ID from a raw string or URL."""
    raw = raw.strip()
    match = re.search(r"[?&]user=([A-Za-z0-9_-]+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return raw
    return raw


@eel.expose
def get_researchers():
    """Return list of all active researchers with latest snapshot and deltas."""
    session = _get_session()
    try:
        researchers = (
            session.query(Researcher)
            .filter(Researcher.is_active.is_(True))
            .all()
        )

        result = []
        for r in researchers:
            recent_snaps = (
                session.query(ResearcherSnapshot)
                .filter(ResearcherSnapshot.researcher_id == r.id)
                .order_by(ResearcherSnapshot.recorded_at.desc())
                .limit(2)
                .all()
            )
            latest = recent_snaps[0] if recent_snaps else None
            previous = recent_snaps[1] if len(recent_snaps) >= 2 else None

            pub_count = session.query(Publication).filter(
                Publication.researcher_id == r.id
            ).count()

            deltas = None
            if latest and previous:
                deltas = {
                    "citations": (latest.total_citations or 0) - (previous.total_citations or 0),
                    "h_index": (latest.h_index or 0) - (previous.h_index or 0),
                    "i10_index": (latest.i10_index or 0) - (previous.i10_index or 0),
                    "since": previous.recorded_at.strftime("%b %d, %Y"),
                }

            result.append({
                "id": r.id,
                "scholar_id": r.scholar_id,
                "name": r.name,
                "affiliation": r.affiliation or "",
                "pub_count": pub_count,
                "total_citations": latest.total_citations if latest else None,
                "h_index": latest.h_index if latest else None,
                "i10_index": latest.i10_index if latest else None,
                "last_scraped_at": r.last_scraped_at.strftime("%Y-%m-%d %H:%M") if r.last_scraped_at else None,
                "deltas": deltas,
            })

        return result
    finally:
        session.close()


@eel.expose
def get_researcher_detail(scholar_id):
    """Return full detail for a researcher: metrics, charts (Plotly JSON), publications."""
    session = _get_session()
    try:
        researcher = session.query(Researcher).filter(
            Researcher.scholar_id == scholar_id
        ).first()
        if not researcher:
            return {"error": "Researcher not found"}

        calc = MetricsCalculator(session)
        metrics = calc.compute(scholar_id)
        computed_h, h_candidates = calc.h_index_candidates(scholar_id)

        # Generate chart JSON
        cite_fig = charts.citation_timeline(session, researcher.id)
        h_fig = charts.h_index_timeline(session, researcher.id)
        h_boundary_fig = charts.h_index_boundary(session, researcher.id)
        vel_fig = charts.velocity_chart(session, researcher.id)
        top_fig = charts.top_papers_bar(session, researcher.id)
        cpy_fig = charts.cites_per_year_bar(session, researcher.id)

        chart_json = {
            "citations": json.loads(cite_fig.to_json()),
            "h_index": json.loads(h_fig.to_json()),
            "h_boundary": json.loads(h_boundary_fig.to_json()),
            "velocity": json.loads(vel_fig.to_json()),
            "top_papers": json.loads(top_fig.to_json()),
            "cites_per_year": json.loads(cpy_fig.to_json()),
        }

        # Publications with citation data
        publications = (
            session.query(Publication)
            .filter(Publication.researcher_id == researcher.id)
            .all()
        )

        pub_data = []
        for pub in publications:
            recent = (
                session.query(CitationSnapshot)
                .filter(CitationSnapshot.publication_id == pub.id)
                .order_by(CitationSnapshot.recorded_at.desc())
                .limit(2)
                .all()
            )
            current = recent[0].citation_count if recent else 0
            delta = None
            if len(recent) >= 2:
                delta = recent[0].citation_count - recent[1].citation_count
            pub_data.append({
                "id": pub.id,
                "title": pub.title,
                "year": pub.year,
                "venue": pub.venue,
                "authors": pub.authors,
                "citations": current,
                "delta": delta,
            })
        pub_data.sort(key=lambda x: x["citations"], reverse=True)

        interests = json.loads(researcher.interests) if researcher.interests else []

        snapshot_count = (
            session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.researcher_id == researcher.id)
            .count()
        )

        # Scrape run info for delta labels
        scrape_runs = (
            session.query(ScrapeRun)
            .filter(ScrapeRun.status == "completed")
            .order_by(ScrapeRun.completed_at.desc())
            .limit(2)
            .all()
        )
        pub_delta_since = scrape_runs[1].completed_at.strftime("%b %d, %Y") if len(scrape_runs) >= 2 else None

        metrics_dict = None
        if metrics:
            metrics_dict = {
                "total_citations": metrics.total_citations,
                "h_index": metrics.h_index,
                "i10_index": metrics.i10_index,
                "num_publications": metrics.num_publications,
                "citation_velocity": round(metrics.citation_velocity, 4),
                "citation_acceleration": round(metrics.citation_acceleration, 4),
                "citation_half_life": metrics.citation_half_life,
                "trending_papers": [
                    {
                        "title": p.title,
                        "current_citations": p.current_citations,
                        "new_citations_7d": p.new_citations_7d,
                        "new_citations_30d": p.new_citations_30d,
                        "velocity": round(p.velocity, 4),
                        "citation_delta": p.citation_delta,
                    }
                    for p in metrics.trending_papers
                ],
                "declining_papers": [
                    {
                        "title": p.title,
                        "current_citations": p.current_citations,
                        "citation_delta": p.citation_delta,
                    }
                    for p in metrics.declining_papers
                ],
            }

        h_candidates_list = [
            {
                "title": c.title,
                "publication_id": c.publication_id,
                "current_citations": c.current_citations,
                "citations_needed": c.citations_needed,
                "velocity": round(c.velocity, 4),
                "days_to_h": c.days_to_h,
            }
            for c in h_candidates
        ]

        return {
            "researcher": {
                "id": researcher.id,
                "scholar_id": researcher.scholar_id,
                "name": researcher.name,
                "affiliation": researcher.affiliation or "",
                "last_scraped_at": researcher.last_scraped_at.strftime("%Y-%m-%d %H:%M") if researcher.last_scraped_at else None,
            },
            "metrics": metrics_dict,
            "charts": chart_json,
            "publications": pub_data,
            "interests": interests,
            "snapshot_count": snapshot_count,
            "pub_delta_since": pub_delta_since,
            "computed_h": computed_h,
            "h_candidates": h_candidates_list,
        }
    finally:
        session.close()


@eel.expose
def get_publication_detail(pub_id):
    """Return publication info + citation chart JSON."""
    session = _get_session()
    try:
        pub = session.query(Publication).get(pub_id)
        if not pub:
            return {"error": "Publication not found"}

        researcher = session.query(Researcher).get(pub.researcher_id)
        fig = charts.publication_citation_timeline(session, pub_id)

        snapshots = (
            session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub_id)
            .order_by(CitationSnapshot.recorded_at.desc())
            .all()
        )

        return {
            "publication": {
                "id": pub.id,
                "title": pub.title,
                "year": pub.year,
                "venue": pub.venue,
                "authors": pub.authors,
                "url": pub.url,
            },
            "researcher": {
                "scholar_id": researcher.scholar_id,
                "name": researcher.name,
            } if researcher else None,
            "chart": json.loads(fig.to_json()),
            "snapshots": [
                {
                    "date": s.recorded_at.strftime("%Y-%m-%d %H:%M"),
                    "citation_count": s.citation_count,
                }
                for s in snapshots
            ],
        }
    finally:
        session.close()


@eel.expose
def get_comparison_data(researcher_ids):
    """Return comparison chart JSON + metrics for given researcher IDs."""
    session = _get_session()
    try:
        fig = charts.comparison_chart(session, researcher_ids)
        calc = MetricsCalculator(session)

        comparison_data = []
        for rid in researcher_ids:
            researcher = session.query(Researcher).get(rid)
            if not researcher:
                continue
            metrics = calc.compute(researcher.scholar_id)
            if metrics:
                comparison_data.append({
                    "researcher": {
                        "id": researcher.id,
                        "scholar_id": researcher.scholar_id,
                        "name": researcher.name,
                    },
                    "metrics": {
                        "total_citations": metrics.total_citations,
                        "h_index": metrics.h_index,
                        "i10_index": metrics.i10_index,
                        "num_publications": metrics.num_publications,
                        "citation_velocity": round(metrics.citation_velocity, 4),
                        "citation_acceleration": round(metrics.citation_acceleration, 4),
                    },
                })

        return {
            "chart": json.loads(fig.to_json()),
            "data": comparison_data,
        }
    finally:
        session.close()


@eel.expose
def add_researcher(scholar_id_or_url):
    """Add a researcher to the database. Returns success/error dict."""
    scholar_id = _extract_scholar_id(scholar_id_or_url)
    if not scholar_id:
        return {"error": "Please enter a Google Scholar ID."}

    session = _get_session()
    try:
        existing = session.query(Researcher).filter(
            Researcher.scholar_id == scholar_id
        ).first()

        if existing:
            if not existing.is_active:
                existing.is_active = True
                session.commit()
                return {"success": True, "message": f"Re-activated {existing.name}."}
            return {"error": f"Already tracking {existing.name}."}

        if not re.fullmatch(r"[A-Za-z0-9_-]{8,20}", scholar_id):
            return {
                "error": f"'{scholar_id}' doesn't look like a valid Google Scholar ID. "
                "IDs are typically 12 characters of letters, numbers, dashes, and underscores."
            }

        researcher = Researcher(
            scholar_id=scholar_id,
            name=scholar_id,
            is_active=True,
        )
        session.add(researcher)
        session.commit()
        return {
            "success": True,
            "message": f"Added {scholar_id}. Data will appear after the next scrape.",
        }
    finally:
        session.close()


@eel.expose
def remove_researcher(researcher_id):
    """Deactivate a researcher."""
    session = _get_session()
    try:
        researcher = session.query(Researcher).get(researcher_id)
        if researcher:
            researcher.is_active = False
            session.commit()
            return {"success": True}
        return {"error": "Researcher not found"}
    finally:
        session.close()


@eel.expose
def trigger_scrape(scholar_id=None):
    """Run scrape in a background thread. Returns immediately with status."""
    global _scrape_running
    if _scrape_running:
        return {"error": "A scrape is already running."}

    def _run():
        global _scrape_running
        _scrape_running = True
        try:
            from ..scraper import ScholarScraper
            session = _get_session()
            try:
                scraper = ScholarScraper(_config, session)
                if scholar_id:
                    run = scraper.scrape_one(scholar_id)
                else:
                    run = scraper.scrape_all()

                # Generate notifications
                from ..notifications import NotificationGenerator
                gen = NotificationGenerator(session)
                gen.generate_for_scrape_run(run)

                eel.on_scrape_complete({
                    "status": run.status,
                    "researchers_scraped": run.researchers_scraped,
                    "publications_found": run.publications_found,
                    "error": run.error_message,
                })
            finally:
                session.close()
        except Exception as e:
            logger.exception("Scrape failed")
            eel.on_scrape_complete({"status": "error", "error": str(e)})
        finally:
            _scrape_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"success": True, "message": "Scrape started..."}


@eel.expose
def get_scrape_status():
    """Check if a scrape is currently running."""
    return {"running": _scrape_running}


@eel.expose
def get_notifications():
    """Return recent notifications."""
    session = _get_session()
    try:
        notifs = (
            session.query(Notification)
            .order_by(Notification.created_at.desc())
            .limit(100)
            .all()
        )
        return [
            {
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%b %d, %H:%M"),
                "researcher_id": n.researcher_id,
            }
            for n in notifs
        ]
    finally:
        session.close()


@eel.expose
def mark_notification_read(notif_id):
    """Mark a single notification as read."""
    session = _get_session()
    try:
        notif = session.query(Notification).get(notif_id)
        if notif:
            notif.is_read = True
            session.commit()
        return {"success": True}
    finally:
        session.close()


@eel.expose
def mark_all_read():
    """Mark all notifications as read."""
    session = _get_session()
    try:
        session.query(Notification).filter(
            Notification.is_read.is_(False)
        ).update({Notification.is_read: True})
        session.commit()
        return {"success": True}
    finally:
        session.close()


@eel.expose
def get_all_researchers():
    """Return all active researchers (minimal info, for compare page)."""
    session = _get_session()
    try:
        researchers = (
            session.query(Researcher)
            .filter(Researcher.is_active.is_(True))
            .all()
        )
        return [
            {"id": r.id, "scholar_id": r.scholar_id, "name": r.name}
            for r in researchers
        ]
    finally:
        session.close()


@eel.expose
def get_unread_count():
    """Return the number of unread notifications."""
    session = _get_session()
    try:
        count = session.query(Notification).filter(
            Notification.is_read.is_(False)
        ).count()
        return count
    finally:
        session.close()
