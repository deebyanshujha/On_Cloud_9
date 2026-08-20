"""API response shapes (Step 8). These wrap the existing `Signal` shape
(app/schemas/document.py) with a few fields the frontend needs and
shouldn't have to compute itself — source counts, a source-type breakdown,
and the date a pairing was first seen. No new business logic: everything
here is read off of a Signal's existing `supporting_documents`.
"""
from __future__ import annotations

from collections import Counter
from datetime import date as date_

from pydantic import BaseModel

from app.schemas.document import Signal


class SourceLink(BaseModel):
    """One piece of supporting evidence, with a real link back to the
    original source (ClinicalTrials.gov study, Europe PMC preprint)."""

    source: str
    source_id: str
    url: str | None
    date: date_ | None
    phase: str | None
    evidence_type: str | None = None


class SignalOut(BaseModel):
    drug: str
    disease: str
    score: float
    reasons: list[str]
    approved_for: list[str]
    num_independent_sources: int
    source_breakdown: dict[str, int]
    first_detected: date_ | None
    sources: list[SourceLink]


class TerminologyEntry(BaseModel):
    """One clean, structured autocomplete entity — never a raw label
    paragraph or trial title (see app.core.terminology)."""

    name: str


class TerminologySearchOut(BaseModel):
    results: list[TerminologyEntry]
    source_unavailable: bool = False


class SearchResultsOut(BaseModel):
    """Bounded, ranked page of /search results (2026-08-20 fix — see
    PROGRESS.md). `total` is the full match count before limit/offset are
    applied, so the frontend can show "N of M" and offer a "load more" page
    without a second round-trip just to find out how many there are."""

    results: list[SignalOut]
    total: int
    limit: int
    offset: int


def build_signal_out(signal: Signal) -> SignalOut:
    docs = signal.supporting_documents
    dated = [d.date for d in docs if d.date is not None]

    sources = sorted(
        (
            SourceLink(
                source=d.source,
                source_id=d.source_id,
                url=d.url,
                date=d.date,
                phase=d.phase,
                evidence_type=d.evidence_type,
            )
            for d in docs
        ),
        key=lambda s: s.date or date_.min,
        reverse=True,
    )

    return SignalOut(
        drug=signal.drug,
        disease=signal.disease,
        score=signal.score,
        reasons=signal.reasons,
        approved_for=signal.approved_for,
        num_independent_sources=len({d.source_id for d in docs}),
        source_breakdown=dict(Counter(d.source for d in docs)),
        first_detected=min(dated) if dated else None,
        sources=sources,
    )
