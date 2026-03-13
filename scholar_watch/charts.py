"""Plotly chart builders for the dashboard and email reports."""

from datetime import datetime

import plotly.graph_objects as go
from sqlalchemy.orm import Session

from .models import CitationSnapshot, Publication, Researcher, ResearcherSnapshot


def citation_timeline(session: Session, researcher_id: int) -> go.Figure:
    """Total citation count over time for a researcher."""
    snapshots = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher_id)
        .order_by(ResearcherSnapshot.recorded_at)
        .all()
    )

    dates = [s.recorded_at for s in snapshots]
    citations = [s.total_citations or 0 for s in snapshots]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=citations,
        mode="lines+markers",
        name="Total Citations",
        line=dict(color="#2563eb", width=2),
        marker=dict(size=6),
    ))
    fig.update_layout(
        title="Total Citations Over Time",
        xaxis_title="Date",
        yaxis_title="Citations",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig


def h_index_timeline(session: Session, researcher_id: int) -> go.Figure:
    """H-index over time for a researcher."""
    snapshots = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher_id)
        .order_by(ResearcherSnapshot.recorded_at)
        .all()
    )

    dates = [s.recorded_at for s in snapshots]
    h_values = [s.h_index or 0 for s in snapshots]
    i10_values = [s.i10_index or 0 for s in snapshots]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=h_values,
        mode="lines+markers", name="h-index",
        line=dict(color="#2563eb", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=i10_values,
        mode="lines+markers", name="i10-index",
        line=dict(color="#dc2626", width=2),
    ))
    fig.update_layout(
        title="h-index & i10-index Over Time",
        xaxis_title="Date",
        yaxis_title="Index Value",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig


def publication_citation_timeline(session: Session, publication_id: int) -> go.Figure:
    """Citation count over time for a single publication."""
    snapshots = (
        session.query(CitationSnapshot)
        .filter(CitationSnapshot.publication_id == publication_id)
        .order_by(CitationSnapshot.recorded_at)
        .all()
    )

    pub = session.query(Publication).get(publication_id)
    title = pub.title[:60] + "..." if pub and len(pub.title) > 60 else (pub.title if pub else "")

    dates = [s.recorded_at for s in snapshots]
    counts = [s.citation_count for s in snapshots]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=counts,
        mode="lines+markers", name="Citations",
        line=dict(color="#2563eb", width=2),
        fill="tozeroy", fillcolor="rgba(37, 99, 235, 0.1)",
    ))
    fig.update_layout(
        title=f"Citations: {title}",
        xaxis_title="Date",
        yaxis_title="Citation Count",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig


def top_papers_bar(session: Session, researcher_id: int, limit: int = 15) -> go.Figure:
    """Bar chart of top-cited publications for a researcher."""
    # Get latest citation count per publication
    publications = (
        session.query(Publication)
        .filter(Publication.researcher_id == researcher_id)
        .all()
    )

    pub_data = []
    for pub in publications:
        latest = (
            session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub.id)
            .order_by(CitationSnapshot.recorded_at.desc())
            .first()
        )
        if latest:
            pub_data.append((pub.title[:50], latest.citation_count))

    pub_data.sort(key=lambda x: x[1], reverse=True)
    pub_data = pub_data[:limit]
    pub_data.reverse()  # Horizontal bar reads bottom-to-top

    titles = [p[0] for p in pub_data]
    counts = [p[1] for p in pub_data]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=titles, x=counts,
        orientation="h",
        marker_color="#2563eb",
    ))
    fig.update_layout(
        title="Top Cited Publications",
        xaxis_title="Citations",
        template="plotly_white",
        margin=dict(l=250, r=30, t=50, b=50),
        height=max(400, len(titles) * 30 + 100),
    )
    return fig


def h_index_boundary(session: Session, researcher_id: int) -> go.Figure:
    """Rank-citation chart showing the h-index boundary and near-threshold papers."""
    publications = (
        session.query(Publication)
        .filter(Publication.researcher_id == researcher_id)
        .all()
    )

    pub_data = []
    for pub in publications:
        latest = (
            session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub.id)
            .order_by(CitationSnapshot.recorded_at.desc())
            .first()
        )
        if latest:
            pub_data.append((pub.title[:50], latest.citation_count))

    pub_data.sort(key=lambda x: x[1], reverse=True)

    if not pub_data:
        fig = go.Figure()
        fig.update_layout(title="h-index Boundary (no data)", template="plotly_white")
        return fig

    # Google Scholar's reported h-index
    scholar_snap = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher_id)
        .order_by(ResearcherSnapshot.recorded_at.desc())
        .first()
    )
    scholar_h = scholar_snap.h_index if scholar_snap else None

    ranks = list(range(1, len(pub_data) + 1))
    counts = [p[1] for p in pub_data]
    titles = [p[0] for p in pub_data]

    # Computed h-index: largest rank where citations >= rank
    h_index = 0
    for r, c in zip(ranks, counts):
        if c >= r:
            h_index = r

    # Color: blue if contributes to h-index, amber if candidate, gray otherwise
    colors = []
    for r, c in zip(ranks, counts):
        if c >= r and r <= h_index:
            colors.append("#2563eb")  # contributes to h-index
        elif r == h_index + 1 or (r > h_index and c >= h_index - 2):
            colors.append("#f59e0b")  # candidate
        else:
            colors.append("#cbd5e1")  # far from threshold

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=ranks, y=counts,
        marker_color=colors,
        hovertext=titles,
        hoverinfo="text+y",
        name="Citations",
    ))

    # Computed h-index threshold line
    fig.add_trace(go.Scatter(
        x=[1, h_index, len(pub_data)],
        y=[h_index, h_index, h_index],
        mode="lines",
        name=f"Computed h = {h_index}",
        line=dict(color="#dc2626", width=2, dash="dash"),
    ))

    # Google Scholar h-index line (if different)
    if scholar_h is not None and scholar_h != h_index:
        fig.add_trace(go.Scatter(
            x=[1, scholar_h, len(pub_data)],
            y=[scholar_h, scholar_h, scholar_h],
            mode="lines",
            name=f"Google Scholar h = {scholar_h}",
            line=dict(color="#16a34a", width=2, dash="dot"),
        ))

    title_parts = [f"h-index Boundary (computed h = {h_index}"]
    if scholar_h is not None and scholar_h != h_index:
        title_parts.append(f", Google Scholar h = {scholar_h}")
    title_parts.append(")")

    fig.update_layout(
        title="".join(title_parts),
        xaxis_title="Paper Rank",
        yaxis_title="Citations",
        yaxis_type="log",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
        showlegend=True,
    )
    return fig


def velocity_chart(session: Session, researcher_id: int) -> go.Figure:
    """Citation velocity (delta between consecutive snapshots) over time."""
    snapshots = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher_id)
        .order_by(ResearcherSnapshot.recorded_at)
        .all()
    )

    if len(snapshots) < 2:
        fig = go.Figure()
        fig.update_layout(
            title="Citation Velocity (insufficient data)",
            template="plotly_white",
        )
        return fig

    dates = []
    deltas = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]
        delta = (curr.total_citations or 0) - (prev.total_citations or 0)
        days = max((curr.recorded_at - prev.recorded_at).total_seconds() / 86400, 1)
        dates.append(curr.recorded_at)
        deltas.append(delta / days)

    colors = ["#16a34a" if d >= 0 else "#dc2626" for d in deltas]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dates, y=deltas,
        marker_color=colors,
        name="Velocity",
    ))
    fig.update_layout(
        title="Citation Velocity (citations/day)",
        xaxis_title="Date",
        yaxis_title="Citations per Day",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig


def comparison_chart(session: Session, researcher_ids: list[int]) -> go.Figure:
    """Compare total citations over time for multiple researchers."""
    fig = go.Figure()
    colors = ["#2563eb", "#dc2626", "#16a34a", "#f59e0b", "#8b5cf6", "#ec4899"]

    for idx, rid in enumerate(researcher_ids):
        researcher = session.query(Researcher).get(rid)
        if not researcher:
            continue

        snapshots = (
            session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.researcher_id == rid)
            .order_by(ResearcherSnapshot.recorded_at)
            .all()
        )

        dates = [s.recorded_at for s in snapshots]
        citations = [s.total_citations or 0 for s in snapshots]

        fig.add_trace(go.Scatter(
            x=dates, y=citations,
            mode="lines+markers",
            name=researcher.name,
            line=dict(color=colors[idx % len(colors)], width=2),
        ))

    fig.update_layout(
        title="Citation Comparison",
        xaxis_title="Date",
        yaxis_title="Total Citations",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig


def cites_per_year_bar(session: Session, researcher_id: int) -> go.Figure:
    """Bar chart of citations per year from the latest researcher snapshot."""
    snapshot = (
        session.query(ResearcherSnapshot)
        .filter(ResearcherSnapshot.researcher_id == researcher_id)
        .order_by(ResearcherSnapshot.recorded_at.desc())
        .first()
    )

    if not snapshot or not snapshot.cites_per_year:
        fig = go.Figure()
        fig.update_layout(title="Citations Per Year (no data)", template="plotly_white")
        return fig

    years = sorted(snapshot.cites_per_year.keys())
    counts = [snapshot.cites_per_year[y] for y in years]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=counts, marker_color="#2563eb"))
    fig.update_layout(
        title="Citations Per Year",
        xaxis_title="Year",
        yaxis_title="Citations",
        template="plotly_white",
        margin=dict(l=50, r=30, t=50, b=50),
    )
    return fig
