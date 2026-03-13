"""Citation metrics calculations."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import CitationSnapshot, Publication, Researcher, ResearcherSnapshot


@dataclass
class PaperMetrics:
    """Metrics for a single publication."""
    title: str
    year: int | None
    current_citations: int
    previous_citations: int | None
    citation_delta: int | None
    velocity: float  # citations per day (30-day window)
    citations_per_year: float | None
    new_citations_7d: int | None = None
    new_citations_30d: int | None = None


@dataclass
class ResearcherMetrics:
    """Computed metrics for a researcher."""
    scholar_id: str
    name: str
    total_citations: int
    h_index: int
    i10_index: int
    num_publications: int
    citation_velocity: float  # total citations gained per day (30-day)
    citation_acceleration: float  # change in velocity between windows
    citation_half_life: float | None  # weighted median age by velocity
    trending_papers: list[PaperMetrics] = field(default_factory=list)
    declining_papers: list[PaperMetrics] = field(default_factory=list)


@dataclass
class HIndexCandidate:
    """A paper near the h-index threshold."""
    title: str
    publication_id: int
    current_citations: int
    citations_needed: int
    velocity: float
    days_to_h: float | None  # estimated days to cross threshold at current velocity


class MetricsCalculator:
    """Computes standard and custom citation metrics."""

    def __init__(self, session: Session, window_days: int = 30):
        self.session = session
        self.window_days = window_days

    def compute(self, scholar_id: str) -> ResearcherMetrics | None:
        """Compute all metrics for a researcher."""
        researcher = (
            self.session.query(Researcher)
            .filter(Researcher.scholar_id == scholar_id)
            .first()
        )
        if not researcher:
            return None

        # Latest researcher snapshot
        latest_snap = (
            self.session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.researcher_id == researcher.id)
            .order_by(ResearcherSnapshot.recorded_at.desc())
            .first()
        )

        total_citations = latest_snap.total_citations if latest_snap else 0
        h_index = latest_snap.h_index if latest_snap else 0
        i10_index = latest_snap.i10_index if latest_snap else 0

        publications = (
            self.session.query(Publication)
            .filter(Publication.researcher_id == researcher.id)
            .all()
        )

        paper_metrics = []
        for pub in publications:
            pm = self._compute_paper_metrics(pub)
            if pm:
                paper_metrics.append(pm)

        velocity = sum(pm.velocity for pm in paper_metrics)
        acceleration = self._compute_acceleration(researcher.id)

        # Trending: top 10 by velocity (positive only)
        trending = sorted(
            [pm for pm in paper_metrics if pm.velocity > 0],
            key=lambda pm: pm.velocity,
            reverse=True,
        )[:10]

        # Declining: negative delta
        declining = sorted(
            [pm for pm in paper_metrics if pm.citation_delta is not None and pm.citation_delta < 0],
            key=lambda pm: pm.citation_delta,
        )

        half_life = self._compute_half_life(paper_metrics)

        return ResearcherMetrics(
            scholar_id=scholar_id,
            name=researcher.name,
            total_citations=total_citations,
            h_index=h_index,
            i10_index=i10_index,
            num_publications=len(publications),
            citation_velocity=velocity,
            citation_acceleration=acceleration,
            citation_half_life=half_life,
            trending_papers=trending,
            declining_papers=declining,
        )

    def _compute_paper_metrics(self, pub: Publication) -> PaperMetrics | None:
        """Compute metrics for a single publication."""
        snapshots = (
            self.session.query(CitationSnapshot)
            .filter(CitationSnapshot.publication_id == pub.id)
            .order_by(CitationSnapshot.recorded_at.desc())
            .all()
        )

        if not snapshots:
            return None

        current = snapshots[0]
        now = datetime.utcnow()
        window_start = now - timedelta(days=self.window_days)

        # Find the snapshot closest to window_start
        window_snapshot = None
        for snap in snapshots:
            if snap.recorded_at <= window_start:
                window_snapshot = snap
                break

        if window_snapshot and window_snapshot.id != current.id:
            delta = current.citation_count - window_snapshot.citation_count
            days_elapsed = (current.recorded_at - window_snapshot.recorded_at).total_seconds() / 86400
            velocity = delta / max(days_elapsed, 1)
        elif len(snapshots) >= 2:
            # Use earliest available if no snapshot before window
            earliest = snapshots[-1]
            delta = current.citation_count - earliest.citation_count
            days_elapsed = (current.recorded_at - earliest.recorded_at).total_seconds() / 86400
            velocity = delta / max(days_elapsed, 1)
        else:
            delta = None
            velocity = 0.0

        previous_citations = snapshots[1].citation_count if len(snapshots) >= 2 else None
        citation_delta = current.citation_count - previous_citations if previous_citations is not None else delta

        # Citations per year (annualized)
        cpy = None
        if pub.year and current.citation_count > 0:
            years = max(now.year - pub.year, 1)
            cpy = current.citation_count / years

        # New citations in last 7 and 30 days
        new_7d = self._citations_since(snapshots, current, now - timedelta(days=7))
        new_30d = self._citations_since(snapshots, current, now - timedelta(days=30))

        return PaperMetrics(
            title=pub.title,
            year=pub.year,
            current_citations=current.citation_count,
            previous_citations=previous_citations,
            citation_delta=citation_delta,
            velocity=velocity,
            citations_per_year=cpy,
            new_citations_7d=new_7d,
            new_citations_30d=new_30d,
        )

    @staticmethod
    def _citations_since(
        snapshots: list, current, cutoff: datetime
    ) -> int | None:
        """Return new citations since the snapshot closest to *cutoff*.

        *snapshots* must be ordered most-recent-first (as returned by
        ``_compute_paper_metrics``).  Returns ``None`` when no snapshot
        exists at or before *cutoff*.
        """
        baseline = None
        for snap in snapshots:
            if snap.recorded_at <= cutoff:
                baseline = snap
                break
        if baseline is None or baseline.id == current.id:
            return None
        return current.citation_count - baseline.citation_count

    def _compute_acceleration(self, researcher_id: int) -> float:
        """Compute citation acceleration (change in velocity between windows)."""
        now = datetime.utcnow()
        window1_start = now - timedelta(days=self.window_days)
        window2_start = now - timedelta(days=self.window_days * 2)

        # Get total citations at three points in time
        def _total_at(before: datetime) -> int | None:
            snap = (
                self.session.query(ResearcherSnapshot)
                .filter(
                    ResearcherSnapshot.researcher_id == researcher_id,
                    ResearcherSnapshot.recorded_at <= before,
                )
                .order_by(ResearcherSnapshot.recorded_at.desc())
                .first()
            )
            return snap.total_citations if snap else None

        current_snap = (
            self.session.query(ResearcherSnapshot)
            .filter(ResearcherSnapshot.researcher_id == researcher_id)
            .order_by(ResearcherSnapshot.recorded_at.desc())
            .first()
        )
        if not current_snap:
            return 0.0

        c_now = current_snap.total_citations or 0
        c_w1 = _total_at(window1_start)
        c_w2 = _total_at(window2_start)

        if c_w1 is not None and c_w2 is not None:
            v_recent = (c_now - c_w1) / self.window_days
            v_prev = (c_w1 - c_w2) / self.window_days
            return v_recent - v_prev

        return 0.0

    def _compute_half_life(self, paper_metrics: list[PaperMetrics]) -> float | None:
        """Compute citation half-life: weighted median age of papers by velocity."""
        now = datetime.utcnow()
        weighted = []
        for pm in paper_metrics:
            if pm.year and pm.velocity > 0:
                age = max(now.year - pm.year, 0)
                weighted.append((age, pm.velocity))

        if not weighted:
            return None

        # Sort by age
        weighted.sort(key=lambda x: x[0])
        total_weight = sum(w for _, w in weighted)
        if total_weight == 0:
            return None

        cumulative = 0.0
        for age, weight in weighted:
            cumulative += weight
            if cumulative >= total_weight / 2:
                return float(age)

        return weighted[-1][0]

    def h_index_candidates(self, scholar_id: str, max_results: int = 10) -> list[HIndexCandidate]:
        """Find papers just below the h-index threshold.

        Returns papers that are closest to pushing the h-index up by one,
        sorted by fewest citations needed (then highest velocity).
        """
        researcher = (
            self.session.query(Researcher)
            .filter(Researcher.scholar_id == scholar_id)
            .first()
        )
        if not researcher:
            return []

        from .models import CitationSnapshot, Publication

        publications = (
            self.session.query(Publication)
            .filter(Publication.researcher_id == researcher.id)
            .all()
        )

        # Get latest citation count + velocity for each publication
        pub_info = []
        for pub in publications:
            pm = self._compute_paper_metrics(pub)
            if pm:
                pub_info.append((pub.id, pub.title, pm.current_citations, pm.velocity))

        # Sort by citations desc to compute h-index
        pub_info.sort(key=lambda x: x[2], reverse=True)

        h_index = 0
        for rank, (_, _, cites, _) in enumerate(pub_info, 1):
            if cites >= rank:
                h_index = rank

        # Target: to increase h to h+1, we need (h+1) papers with >= (h+1) citations.
        # Papers currently at rank <= h already have enough.
        # Papers at rank > h that have fewer than (h+1) citations are candidates.
        target = h_index + 1
        candidates = []
        for rank, (pub_id, title, cites, vel) in enumerate(pub_info, 1):
            if rank <= h_index:
                continue  # already contributing
            needed = target - cites
            if needed <= 0:
                # This paper already has enough — it would push h up
                needed = 0
            if needed > target:
                continue  # too far away to be interesting

            days_to_h = None
            if vel > 0 and needed > 0:
                days_to_h = round(needed / vel, 1)

            candidates.append(HIndexCandidate(
                title=title,
                publication_id=pub_id,
                current_citations=cites,
                citations_needed=needed,
                velocity=vel,
                days_to_h=days_to_h,
            ))

        # Sort: fewest citations needed first, then highest velocity
        candidates.sort(key=lambda c: (c.citations_needed, -c.velocity))
        return h_index, candidates[:max_results]
