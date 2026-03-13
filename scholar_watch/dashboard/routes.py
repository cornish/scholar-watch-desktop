"""Flask routes and API endpoints for the dashboard."""

import json

from flask import Blueprint, current_app, render_template, request, jsonify

from ..config import AppConfig
from ..database import get_session
from ..models import (
    CitationSnapshot,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
)
from ..metrics import MetricsCalculator
from .. import charts

bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


def _get_session():
    config: AppConfig = current_app.config["APP_CONFIG"]
    return get_session(config)


# ── HTML Pages ──────────────────────────────────────────────────────────

@bp.route("/")
def index():
    """Home page: all researchers with summary metrics."""
    session = _get_session()
    try:
        researchers = session.query(Researcher).filter(Researcher.is_active.is_(True)).all()

        researcher_data = []
        for r in researchers:
            # Two most recent snapshots for delta calculation
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

            # Compute deltas
            deltas = None
            if latest and previous:
                deltas = {
                    "citations": (latest.total_citations or 0) - (previous.total_citations or 0),
                    "h_index": (latest.h_index or 0) - (previous.h_index or 0),
                    "i10_index": (latest.i10_index or 0) - (previous.i10_index or 0),
                    "since": previous.recorded_at,
                }

            researcher_data.append({
                "researcher": r,
                "snapshot": latest,
                "previous": previous,
                "deltas": deltas,
                "pub_count": pub_count,
            })

        return render_template("index.html", researchers=researcher_data)
    finally:
        session.close()


@bp.route("/researcher/<scholar_id>")
def researcher_detail(scholar_id: str):
    """Researcher detail page with charts."""
    session = _get_session()
    try:
        researcher = session.query(Researcher).filter(
            Researcher.scholar_id == scholar_id
        ).first()
        if not researcher:
            return render_template("404.html", message="Researcher not found"), 404

        calc = MetricsCalculator(session)
        metrics = calc.compute(scholar_id)
        computed_h, h_candidates = calc.h_index_candidates(scholar_id)

        # Build charts as HTML divs
        cite_fig = charts.citation_timeline(session, researcher.id)
        h_fig = charts.h_index_timeline(session, researcher.id)
        h_boundary_fig = charts.h_index_boundary(session, researcher.id)
        vel_fig = charts.velocity_chart(session, researcher.id)
        top_fig = charts.top_papers_bar(session, researcher.id)
        cpy_fig = charts.cites_per_year_bar(session, researcher.id)

        chart_html = {
            "citations": cite_fig.to_html(full_html=False, include_plotlyjs=False),
            "h_index": h_fig.to_html(full_html=False, include_plotlyjs=False),
            "h_boundary": h_boundary_fig.to_html(full_html=False, include_plotlyjs=False),
            "velocity": vel_fig.to_html(full_html=False, include_plotlyjs=False),
            "top_papers": top_fig.to_html(full_html=False, include_plotlyjs=False),
            "cites_per_year": cpy_fig.to_html(full_html=False, include_plotlyjs=False),
        }

        publications = (
            session.query(Publication)
            .filter(Publication.researcher_id == researcher.id)
            .all()
        )

        # Get latest + previous citation count for each publication
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
                "publication": pub,
                "citations": current,
                "delta": delta,
            })
        pub_data.sort(key=lambda x: x["citations"], reverse=True)

        # "since" date for publication deltas (from 2nd-most-recent scrape run)
        scrape_runs = (
            session.query(ScrapeRun)
            .filter(ScrapeRun.status == "completed")
            .order_by(ScrapeRun.completed_at.desc())
            .limit(2)
            .all()
        )
        pub_delta_since = scrape_runs[1].completed_at if len(scrape_runs) >= 2 else None

        interests = json.loads(researcher.interests) if researcher.interests else []

        return render_template(
            "researcher.html",
            researcher=researcher,
            metrics=metrics,
            charts=chart_html,
            publications=pub_data,
            interests=interests,
            pub_delta_since=pub_delta_since,
            h_candidates=h_candidates,
            computed_h=computed_h,
        )
    finally:
        session.close()


@bp.route("/publication/<int:pub_id>")
def publication_detail(pub_id: int):
    """Publication detail page with citation timeline."""
    session = _get_session()
    try:
        pub = session.query(Publication).get(pub_id)
        if not pub:
            return render_template("404.html", message="Publication not found"), 404

        researcher = session.query(Researcher).get(pub.researcher_id)
        fig = charts.publication_citation_timeline(session, pub_id)
        chart_html = fig.to_html(full_html=False, include_plotlyjs=False)

        snapshots = (
            session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub_id)
            .order_by(CitationSnapshot.recorded_at.desc())
            .all()
        )

        return render_template(
            "publication.html",
            publication=pub,
            researcher=researcher,
            chart_html=chart_html,
            snapshots=snapshots,
        )
    finally:
        session.close()


@bp.route("/compare")
def compare():
    """Compare researchers side by side."""
    session = _get_session()
    try:
        researchers = session.query(Researcher).filter(
            Researcher.is_active.is_(True)
        ).all()

        selected_ids = request.args.getlist("ids", type=int)
        chart_html = ""
        comparison_data = []

        if selected_ids:
            fig = charts.comparison_chart(session, selected_ids)
            chart_html = fig.to_html(full_html=False, include_plotlyjs=False)

            calc = MetricsCalculator(session)
            for r in researchers:
                if r.id in selected_ids:
                    metrics = calc.compute(r.scholar_id)
                    comparison_data.append({"researcher": r, "metrics": metrics})

        return render_template(
            "compare.html",
            researchers=researchers,
            selected_ids=selected_ids,
            chart_html=chart_html,
            comparison_data=comparison_data,
        )
    finally:
        session.close()


# ── JSON API Endpoints ──────────────────────────────────────────────────

@bp.route("/api/researcher/<scholar_id>/citations")
def api_citations(scholar_id: str):
    """Citation timeline data as JSON."""
    session = _get_session()
    try:
        researcher = session.query(Researcher).filter(
            Researcher.scholar_id == scholar_id
        ).first()
        if not researcher:
            return jsonify({"error": "not found"}), 404

        snapshots = (
            session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.researcher_id == researcher.id)
            .order_by(ResearcherSnapshot.recorded_at)
            .all()
        )

        return jsonify({
            "dates": [s.recorded_at.isoformat() for s in snapshots],
            "citations": [s.total_citations or 0 for s in snapshots],
            "h_index": [s.h_index or 0 for s in snapshots],
            "i10_index": [s.i10_index or 0 for s in snapshots],
        })
    finally:
        session.close()


@bp.route("/api/publication/<int:pub_id>/citations")
def api_pub_citations(pub_id: int):
    """Publication citation timeline data as JSON."""
    session = _get_session()
    try:
        snapshots = (
            session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub_id)
            .order_by(CitationSnapshot.recorded_at)
            .all()
        )

        return jsonify({
            "dates": [s.recorded_at.isoformat() for s in snapshots],
            "citations": [s.citation_count for s in snapshots],
        })
    finally:
        session.close()


@bp.route("/api/researcher/<scholar_id>/metrics")
def api_metrics(scholar_id: str):
    """Computed metrics as JSON."""
    session = _get_session()
    try:
        calc = MetricsCalculator(session)
        metrics = calc.compute(scholar_id)
        if not metrics:
            return jsonify({"error": "not found"}), 404

        return jsonify({
            "scholar_id": metrics.scholar_id,
            "name": metrics.name,
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
                    "velocity": round(p.velocity, 4),
                    "citations": p.current_citations,
                    "new_citations_7d": p.new_citations_7d,
                    "new_citations_30d": p.new_citations_30d,
                }
                for p in metrics.trending_papers
            ],
            "declining_papers": [
                {"title": p.title, "delta": p.citation_delta, "citations": p.current_citations}
                for p in metrics.declining_papers
            ],
        })
    finally:
        session.close()
