"""Flask routes and API endpoints for the dashboard."""

import json
import re

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    jsonify,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from ..auth import FlaskUser, hash_password, verify_password
from ..config import AppConfig
from ..database import get_session
from ..models import (
    CitationSnapshot,
    Notification,
    Publication,
    Researcher,
    ResearcherSnapshot,
    ScrapeRun,
    User,
    UserScholar,
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
    if "db_session" in g:
        return g.db_session
    config: AppConfig = current_app.config["APP_CONFIG"]
    return get_session(config)


@bp.context_processor
def inject_unread_count():
    """Make unread notification count available to all templates."""
    if current_user.is_authenticated:
        session = _get_session()
        count = (
            session.query(Notification)
            .filter(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
            )
            .count()
        )
        return {"unread_count": count}
    return {"unread_count": 0}


# ── Auth Routes ────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        session = _get_session()
        user = session.query(User).filter(User.email == email).first()

        if user and verify_password(password, user.password_hash):
            login_user(FlaskUser(user))
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard.index"))

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not display_name or not email or not password:
            return render_template("signup.html", error="All fields are required.")

        if len(password) < 8:
            return render_template("signup.html", error="Password must be at least 8 characters.")

        if password != confirm:
            return render_template("signup.html", error="Passwords do not match.")

        session = _get_session()
        if session.query(User).filter(User.email == email).first():
            return render_template("signup.html", error="An account with this email already exists.")

        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()

        login_user(FlaskUser(user))
        flash("Account created. Welcome!", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("signup.html")


@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("dashboard.login"))


# ── HTML Pages ──────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def index():
    """Home page: user's watched researchers with summary metrics."""
    session = _get_session()

    # Get researchers this user is watching
    user_scholars = (
        session.query(UserScholar)
        .filter(UserScholar.user_id == current_user.id)
        .all()
    )
    watched_ids = {us.researcher_id for us in user_scholars}

    researchers = (
        session.query(Researcher)
        .filter(Researcher.id.in_(watched_ids))
        .all()
    ) if watched_ids else []

    researcher_data = []
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


@bp.route("/researcher/<scholar_id>")
@login_required
def researcher_detail(scholar_id: str):
    """Researcher detail page with charts."""
    session = _get_session()

    researcher = session.query(Researcher).filter(
        Researcher.scholar_id == scholar_id
    ).first()
    if not researcher:
        return render_template("404.html", message="Researcher not found"), 404

    calc = MetricsCalculator(session)
    metrics = calc.compute(scholar_id)
    computed_h, h_candidates = calc.h_index_candidates(scholar_id)

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

    scrape_runs = (
        session.query(ScrapeRun)
        .filter(ScrapeRun.status == "completed")
        .order_by(ScrapeRun.completed_at.desc())
        .limit(2)
        .all()
    )
    pub_delta_since = scrape_runs[1].completed_at if len(scrape_runs) >= 2 else None

    interests = json.loads(researcher.interests) if researcher.interests else []

    # Compute data status for banners
    snapshot_count = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher.id)
        .count()
    )

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
        snapshot_count=snapshot_count,
    )


@bp.route("/publication/<int:pub_id>")
@login_required
def publication_detail(pub_id: int):
    """Publication detail page with citation timeline."""
    session = _get_session()

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


@bp.route("/compare")
@login_required
def compare():
    """Compare researchers side by side."""
    session = _get_session()

    # Show user's watched researchers for comparison
    user_scholars = (
        session.query(UserScholar)
        .filter(UserScholar.user_id == current_user.id)
        .all()
    )
    watched_ids = {us.researcher_id for us in user_scholars}

    researchers = (
        session.query(Researcher)
        .filter(Researcher.id.in_(watched_ids))
        .all()
    ) if watched_ids else []

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


# ── Scholar Management ─────────────────────────────────────────────────

def _extract_scholar_id(raw: str) -> str:
    """Extract a Google Scholar ID from a raw string or URL.

    Handles inputs like:
      - "g9uuZu6YAAAAJ"  (plain ID)
      - "https://scholar.google.com/citations?user=g9uuZu6YAAAAJ"
      - "https://scholar.google.com/citations?user=g9uuZu6YAAAAJ&hl=en"
    """
    raw = raw.strip()
    match = re.search(r"[?&]user=([A-Za-z0-9_-]+)", raw)
    if match:
        return match.group(1)
    # If it looks like a bare ID (alphanumeric + dash/underscore), use as-is
    if re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return raw
    return raw


@bp.route("/scholars/add", methods=["POST"])
@login_required
def add_scholar():
    """Add a scholar to the user's watchlist."""
    scholar_id = _extract_scholar_id(request.form.get("scholar_id", ""))
    if not scholar_id:
        flash("Please enter a Google Scholar ID.", "danger")
        return redirect(url_for("dashboard.index"))

    session = _get_session()

    # Find or create the researcher
    researcher = session.query(Researcher).filter(
        Researcher.scholar_id == scholar_id
    ).first()

    if not researcher:
        # Basic format validation — full verification happens on first scrape
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,20}", scholar_id):
            flash(
                f"'{scholar_id}' doesn't look like a valid Google Scholar ID. "
                "IDs are typically 12 characters of letters, numbers, dashes, and underscores.",
                "danger",
            )
            return redirect(url_for("dashboard.index"))

        researcher = Researcher(
            scholar_id=scholar_id,
            name=scholar_id,  # Updated with real name on first scrape
            is_active=True,
        )
        session.add(researcher)
        session.flush()

    # Check if already watching
    existing = (
        session.query(UserScholar)
        .filter(
            UserScholar.user_id == current_user.id,
            UserScholar.researcher_id == researcher.id,
        )
        .first()
    )

    if existing:
        flash(f"You are already watching {researcher.name}.", "info")
    else:
        us = UserScholar(user_id=current_user.id, researcher_id=researcher.id)
        session.add(us)
        session.commit()
        flash(
            f"Added {researcher.name} to your watchlist. "
            "Data will be available after the next scrape runs.",
            "success",
        )

    return redirect(url_for("dashboard.index"))


@bp.route("/scholars/<int:researcher_id>/remove", methods=["POST"])
@login_required
def remove_scholar(researcher_id: int):
    """Remove a scholar from the user's watchlist."""
    session = _get_session()

    us = (
        session.query(UserScholar)
        .filter(
            UserScholar.user_id == current_user.id,
            UserScholar.researcher_id == researcher_id,
        )
        .first()
    )

    if us:
        researcher = session.query(Researcher).get(researcher_id)
        session.delete(us)

        # If no users are watching this researcher, deactivate them
        remaining = (
            session.query(UserScholar)
            .filter(UserScholar.researcher_id == researcher_id)
            .count()
        )
        if remaining == 0 and researcher:
            researcher.is_active = False

        session.commit()
        flash("Scholar removed from your watchlist.", "success")

    return redirect(url_for("dashboard.index"))


@bp.route("/scholars/<int:researcher_id>/settings", methods=["GET", "POST"])
@login_required
def scholar_settings(researcher_id: int):
    """Notification settings for a scholar."""
    session = _get_session()

    us = (
        session.query(UserScholar)
        .filter(
            UserScholar.user_id == current_user.id,
            UserScholar.researcher_id == researcher_id,
        )
        .first()
    )

    if not us:
        flash("Scholar not found in your watchlist.", "danger")
        return redirect(url_for("dashboard.index"))

    researcher = session.query(Researcher).get(researcher_id)

    if request.method == "POST":
        us.notify_new_publications = "notify_new_publications" in request.form
        us.notify_citation_milestones = "notify_citation_milestones" in request.form
        us.notify_h_index_change = "notify_h_index_change" in request.form
        session.commit()
        flash("Notification settings updated.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template(
        "scholar_settings.html",
        researcher=researcher,
        user_scholar=us,
    )


# ── Notifications ──────────────────────────────────────────────────────

@bp.route("/notifications")
@login_required
def notifications():
    """Show user's notifications."""
    session = _get_session()

    notifs = (
        session.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )

    return render_template("notifications.html", notifications=notifs)


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notif_id: int):
    """Mark a single notification as read."""
    session = _get_session()

    notif = session.query(Notification).get(notif_id)
    if notif and notif.user_id == current_user.id:
        notif.is_read = True
        session.commit()

    return redirect(url_for("dashboard.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    """Mark all notifications as read."""
    session = _get_session()

    session.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False),
    ).update({Notification.is_read: True})
    session.commit()

    return redirect(url_for("dashboard.notifications"))


# ── JSON API Endpoints ──────────────────────────────────────────────────

@bp.route("/api/researcher/<scholar_id>/citations")
@login_required
def api_citations(scholar_id: str):
    """Citation timeline data as JSON."""
    session = _get_session()

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


@bp.route("/api/publication/<int:pub_id>/citations")
@login_required
def api_pub_citations(pub_id: int):
    """Publication citation timeline data as JSON."""
    session = _get_session()

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


@bp.route("/api/researcher/<scholar_id>/metrics")
@login_required
def api_metrics(scholar_id: str):
    """Computed metrics as JSON."""
    session = _get_session()

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
