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
