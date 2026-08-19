"""The arbitrage engine's core IP: compare observed drug-disease mentions
against approved indications (ground truth) and score the ones that don't
match as repurposing signals.

This module has NO dependency on any data source, database, or web
framework. It only knows about Document / ApprovedIndication / Signal
(see app/schemas/document.py). That's deliberate: it lets us prove the
logic works with a small hardcoded JSON file before any real ingestion
exists (see backend/data/known_cases.json + tests/test_scoring.py).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from app.core.disease_matching import diseases_match, is_junk_condition
from app.schemas.document import ApprovedIndication, Document, Signal

# --- scoring weights -------------------------------------------------------
# These are intentionally simple, hand-tuned weights for a hackathon demo,
# not a calibrated statistical model. Each component contributes 0-~0.3 and
# the total is clipped to [0, 1].

SOURCE_WEIGHT = {
    "clinicaltrials": 0.40,
    "biorxiv": 0.25,
    "medrxiv": 0.25,
    "manual": 0.30,
}

PHASE_WEIGHT = {
    "phase 4": 0.35,
    "phase 3": 0.30,
    "phase 2": 0.20,
    "phase 1": 0.10,
    "early phase 1": 0.05,
    "not applicable": 0.05,
}
DEFAULT_PHASE_WEIGHT = 0.05

MENTION_WEIGHT_PER_DOC = 0.10
MENTION_WEIGHT_CAP = 0.30

RECENCY_BUCKETS = (
    (365, 0.20),      # <= 1 year old
    (365 * 3, 0.12),  # <= 3 years old
    (365 * 5, 0.06),  # <= 5 years old
)
RECENCY_WEIGHT_STALE = 0.02


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _recency_weight(doc_date: date | None, today: date) -> float:
    if doc_date is None:
        return RECENCY_WEIGHT_STALE
    age_days = (today - doc_date).days
    for max_age_days, weight in RECENCY_BUCKETS:
        if age_days <= max_age_days:
            return weight
    return RECENCY_WEIGHT_STALE


def _phase_weight(phase: str | None) -> float:
    if not phase:
        return DEFAULT_PHASE_WEIGHT
    return PHASE_WEIGHT.get(normalize(phase), DEFAULT_PHASE_WEIGHT)


def _best_source_weight(docs: list[Document]) -> float:
    return max(SOURCE_WEIGHT.get(d.source, 0.2) for d in docs)


def _best_phase_weight(docs: list[Document]) -> float:
    return max(_phase_weight(d.phase) for d in docs)


def _most_recent_weight(docs: list[Document], today: date) -> float:
    return max(_recency_weight(d.date, today) for d in docs)


def _mention_weight(docs: list[Document]) -> float:
    independent_mentions = len({d.source_id for d in docs})
    return min(independent_mentions * MENTION_WEIGHT_PER_DOC, MENTION_WEIGHT_CAP)


def is_already_approved(
    drug: str, disease: str, approved_index: dict[str, list[str]]
) -> bool:
    """True if `disease` matches any approved-indication text for `drug`,
    using the staging/qualifier-aware token matching in
    app/core/disease_matching.py (see that module for why exact string
    matching wasn't sufficient — it was proven wrong by real Step 3/4
    data)."""
    approved_diseases = approved_index.get(normalize(drug), [])
    return any(diseases_match(disease, approved) for approved in approved_diseases)


def build_approved_index(
    approved: Iterable[ApprovedIndication],
) -> dict[str, list[str]]:
    """Maps normalized drug -> list of raw approved-indication disease
    texts (not pre-normalized/deduped into a set, since openFDA entries can
    be long free-text paragraphs rather than clean short phrases — matching
    happens token-wise in diseases_match, not via set membership)."""
    index: dict[str, list[str]] = defaultdict(list)
    for a in approved:
        index[a.normalized_drug()].append(a.disease)
    return index


def group_documents_by_pair(
    documents: Iterable[Document],
) -> dict[tuple[str, str], list[Document]]:
    """Drops documents whose disease is junk (generic trial-eligibility
    terms, study-description sentences — see is_junk_condition) before
    grouping, so junk never reaches scoring/signal output."""
    groups: dict[tuple[str, str], list[Document]] = defaultdict(list)
    for doc in documents:
        if is_junk_condition(doc.disease):
            continue
        key = (doc.normalized_drug(), doc.normalized_disease())
        groups[key].append(doc)
    return groups


def score_pair(docs: list[Document], today: date) -> tuple[float, list[str]]:
    source_w = _best_source_weight(docs)
    phase_w = _best_phase_weight(docs)
    recency_w = _most_recent_weight(docs, today)
    mention_w = _mention_weight(docs)

    total = round(min(source_w + phase_w + recency_w + mention_w, 1.0), 3)

    reasons = []
    best_source = max(docs, key=lambda d: SOURCE_WEIGHT.get(d.source, 0.2)).source
    reasons.append(f"source: {best_source}")
    best_phase_doc = max(docs, key=lambda d: _phase_weight(d.phase))
    if best_phase_doc.phase:
        reasons.append(f"trial phase: {best_phase_doc.phase}")
    independent_mentions = len({d.source_id for d in docs})
    reasons.append(
        f"{independent_mentions} independent mention"
        f"{'s' if independent_mentions != 1 else ''}"
    )
    if recency_w >= 0.20:
        reasons.append("recent (within 1 year)")
    elif recency_w <= RECENCY_WEIGHT_STALE:
        reasons.append("older evidence")

    return total, reasons


def run_comparison(
    documents: Iterable[Document],
    approved: Iterable[ApprovedIndication],
    today: date | None = None,
) -> list[Signal]:
    """The core arbitrage step: for every observed (drug, disease) pair not
    already in the approved-indications ground truth, produce a scored
    Signal. Returns signals sorted by score, highest first."""
    today = today or date.today()

    documents = list(documents)
    approved = list(approved)

    approved_index = build_approved_index(approved)
    approved_for_drug: dict[str, list[str]] = defaultdict(list)
    for a in approved:
        approved_for_drug[a.normalized_drug()].append(a.disease)

    signals: list[Signal] = []
    for (drug, disease), docs in group_documents_by_pair(documents).items():
        if is_already_approved(drug, disease, approved_index):
            continue  # not new — this drug is already approved for this disease

        score, reasons = score_pair(docs, today)
        signals.append(
            Signal(
                drug=drug,
                disease=disease,
                score=score,
                reasons=reasons,
                supporting_documents=docs,
                approved_for=approved_for_drug.get(drug, []),
            )
        )

    signals.sort(key=lambda s: s.score, reverse=True)
    return signals
