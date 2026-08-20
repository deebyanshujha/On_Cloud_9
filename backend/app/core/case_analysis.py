"""TheraLens case-analysis engine.

Given a Case (primary condition + comorbidities + current medications),
produces a ranked list of repurposing candidates for the primary condition,
each annotated with a per-comorbidity safety/context check and a "Research
Priority" score.

Deliberately reuses the existing infrastructure rather than reimplementing
it:
- `app.core.scoring.run_comparison` — the existing drug-discovery/scoring
  pipeline. A candidate is anything it already flags as a new (not-yet-
  approved) drug-disease signal.
- `app.core.disease_matching.diseases_match` — the same token-subset
  matching already used for "is this disease already approved," reused here
  to match a case's free-text primary condition against a signal's disease
  text.
- `app.core.context_check` — the comorbidity-vs-label-text check (see that
  module for the three-state design).

No new drug-discovery or disease-matching logic lives here — this module is
purely: filter existing signals to this case's condition, then layer
case-context (comorbidity conflicts) on top of each one's existing score.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date as date_, datetime
from typing import Iterable

from app.core.config import MAX_CANDIDATES_PER_CASE
from app.core.context_check import check_comorbidity_conflict, combine_states
from app.core.disease_matching import diseases_match
from app.core.scoring import normalize, run_comparison
from app.schemas.case import (
    CandidateOut,
    ComorbidityCheck,
    CurrentMedicationInteractionNote,
    SupportingEvidence,
)
from app.schemas.document import ApprovedIndication, Document, Signal

# --- Research Priority formula ---------------------------------------------
# research_priority_score = clip(
#     evidence_strength_score          # the signal's existing score, from
#                                       # app/core/scoring.py's run_comparison
#     - conflict_penalty                # comorbidity conflicts detected
#     - insufficient_evidence_penalty,  # comorbidities we couldn't check
#     0.0, 1.0
# )
#
# conflict_penalty = min(CONFLICT_PENALTY_CAP, CONFLICT_PENALTY_PER_HIT * num_conflicts)
# insufficient_evidence_penalty = min(
#     INSUFFICIENT_PENALTY_CAP, INSUFFICIENT_PENALTY_PER_HIT * num_insufficient
# )
#
# Rationale: a detected contraindication/warning conflict is real negative
# evidence and should meaningfully lower research priority (0.15 per
# comorbidity, capped at 0.3 so a case with many comorbidities doesn't
# trivially zero out every candidate). Missing/insufficient label data is
# NOT negative evidence — it's uncertainty — so it gets a much smaller
# per-hit penalty (0.03, capped at 0.1), enough to make "well-documented,
# clean" candidates rank above "same score, but we couldn't check anything"
# candidates, without punishing candidates for a data gap that isn't their
# fault.
CONFLICT_PENALTY_PER_HIT = 0.15
CONFLICT_PENALTY_CAP = 0.30
INSUFFICIENT_PENALTY_PER_HIT = 0.03
INSUFFICIENT_PENALTY_CAP = 0.10


def _condition_matches(a: str, b: str) -> bool:
    """Case primary-condition text and a signal's disease text are both
    free-text disease mentions of comparable specificity (unlike
    indication-vs-observed, neither side is reliably "the more specific
    one") — so check both directions of the existing token-subset matcher
    rather than picking one as authoritative."""
    return diseases_match(a, b) or diseases_match(b, a)


def _build_drug_label_index(
    approved: Iterable[ApprovedIndication],
) -> dict[str, list[ApprovedIndication]]:
    index: dict[str, list[ApprovedIndication]] = defaultdict(list)
    for a in approved:
        index[a.normalized_drug()].append(a)
    return index


def _research_priority_score(
    evidence_strength_score: float, comorbidity_checks: list[ComorbidityCheck]
) -> float:
    num_conflicts = sum(1 for c in comorbidity_checks if c.status == "conflict_detected")
    num_insufficient = sum(
        1 for c in comorbidity_checks if c.status == "insufficient_evidence"
    )
    conflict_penalty = min(CONFLICT_PENALTY_CAP, CONFLICT_PENALTY_PER_HIT * num_conflicts)
    insufficient_penalty = min(
        INSUFFICIENT_PENALTY_CAP, INSUFFICIENT_PENALTY_PER_HIT * num_insufficient
    )
    score = evidence_strength_score - conflict_penalty - insufficient_penalty
    return round(max(0.0, min(1.0, score)), 3)


def _reasoning_trail(
    signal: Signal,
    comorbidity_checks: list[ComorbidityCheck],
    research_priority_score: float,
) -> list[str]:
    trail: list[str] = []
    if signal.approved_for:
        trail.append(
            "Currently approved for: " + "; ".join(signal.approved_for)
        )
    else:
        trail.append("We don't have approval records for this drug yet.")

    trail.append(
        f"'{signal.drug}' is being studied for '{signal.disease}', which it "
        "isn't currently approved to treat."
    )

    trail.append(
        "Supporting studies/documents: "
        + "; ".join(
            f"{d.source}:{d.source_id}" for d in signal.supporting_documents
        )
    )

    trail.append(
        f"Evidence strength: {evidence_strength_score(signal)} "
        f"({evidence_tier(evidence_strength_score(signal)).title()})"
    )

    if comorbidity_checks:
        for check in comorbidity_checks:
            if check.status == "conflict_detected":
                trail.append(
                    f"Possible conflict with '{check.comorbidity}' — the drug "
                    f"label warns about this — \"{check.evidence}\" — a "
                    "clinician should review it."
                )
            elif check.status == "no_conflict_detected":
                trail.append(
                    f"No warning found for '{check.comorbidity}' in the drug label."
                )
            else:
                trail.append(
                    f"Not enough label data yet to check '{check.comorbidity}'."
                )
    else:
        trail.append("No comorbidities recorded for this case — no context checks run.")

    trail.append(f"Final research priority score: {research_priority_score}")
    return trail


def evidence_strength_score(signal: Signal) -> float:
    return signal.score


# Mirrors frontend/src/scoring.ts's scoreTier exactly (same thresholds,
# same "insufficient" band for a score of exactly 0) so the tier a backend
# evidence-check diff reports ("MODERATE -> HIGH") always matches what the
# candidate card already shows for that score.
def evidence_tier(score: float) -> str:
    if score <= 0:
        return "insufficient"
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "moderate"
    return "low"


_SOURCE_LABEL = {
    "clinicaltrials": "clinical trial",
    "biorxiv": "publication",
    "medrxiv": "publication",
    "europepmc": "publication",
    "pubmed": "publication",
}


def _evidence_tier_reason(signal: Signal) -> str:
    """Short, human-readable basis for the tier — built from real counts
    already on the signal's supporting documents, never fabricated."""
    counts = Counter(
        _SOURCE_LABEL.get(d.source, d.source) for d in signal.supporting_documents
    )
    if not counts:
        return "No supporting evidence found."
    parts = [f"{n} {label}{'s' if n != 1 else ''}" for label, n in counts.items()]
    return ", ".join(parts)


def _supporting_evidence(signal: Signal) -> list[SupportingEvidence]:
    return [
        SupportingEvidence(
            source=d.source,
            source_id=d.source_id,
            url=d.url,
            date=d.date,
            phase=d.phase,
            evidence_type=d.evidence_type,
        )
        for d in signal.supporting_documents
    ]


def analyze_case(
    primary_condition: str,
    comorbidities: list[str],
    documents: Iterable[Document],
    approved: Iterable[ApprovedIndication],
    today: date_ | None = None,
    target_conditions: list[str] | None = None,
) -> list[CandidateOut]:
    """Runs the full case-analysis flow and returns candidates sorted by
    research_priority_score, highest first."""
    approved = list(approved)
    documents = list(documents)

    signals = run_comparison(documents, approved, today=today)
    drug_labels = _build_drug_label_index(approved)

    targets = []
    for condition in [primary_condition] + (target_conditions or []):
        normalized = normalize(condition)
        if normalized and normalized not in targets:
            targets.append(normalized)

    candidates: list[CandidateOut] = []
    for signal in signals:
        if not any(_condition_matches(target, signal.disease) for target in targets):
            continue

        comorbidity_checks: list[ComorbidityCheck] = []
        for comorbidity in comorbidities:
            labels = drug_labels.get(normalize(signal.drug), [])
            per_label_results = [
                check_comorbidity_conflict(
                    comorbidity, label.contraindications, label.warnings
                )
                for label in labels
            ]
            state, evidence = combine_states(per_label_results)
            comorbidity_checks.append(
                ComorbidityCheck(comorbidity=comorbidity, status=state, evidence=evidence)
            )

        score = _research_priority_score(evidence_strength_score(signal), comorbidity_checks)
        candidates.append(
            CandidateOut(
                drug=signal.drug,
                disease=signal.disease,
                research_priority_score=score,
                evidence_strength_score=evidence_strength_score(signal),
                known_indications=signal.approved_for,
                evidence_tier=evidence_tier(evidence_strength_score(signal)),
                evidence_tier_reason=_evidence_tier_reason(signal),
                primary_condition_evidence=_supporting_evidence(signal),
                comorbidity_checks=comorbidity_checks,
                current_medication_interactions=CurrentMedicationInteractionNote(),
                reasoning_trail=_reasoning_trail(signal, comorbidity_checks, score),
            )
        )

    candidates.sort(key=lambda c: c.research_priority_score, reverse=True)
    # Cap to the top-N most relevant candidates (see config.MAX_CANDIDATES_PER_CASE)
    # — a case page answers "what's worth investigating," not an exhaustive
    # signal dump.
    return candidates[:MAX_CANDIDATES_PER_CASE]
