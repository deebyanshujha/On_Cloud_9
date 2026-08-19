"""Phase 3: diffing a saved case's analysis snapshot against a fresh
re-analysis to detect "new evidence" — the manually-triggered alternative
to true continuous background monitoring (Step 7's scheduler stays
deferred; see PROGRESS.md).

Scope, deliberately small per the brief:
- which candidates changed evidence-strength tier/score
- which candidates gained new supporting studies/trials (real source_ids
  not present in the snapshot)
- whether any candidate gained a new context conflict
- which candidates are entirely new since the snapshot

A drug can appear as more than one `CandidateOut` in a single analysis (one
per matched disease-text variant of the case's primary condition — see
`case_analysis.py`), so comparison happens per-drug on an aggregate: the
best (max) evidence score, the union of all real supporting source_ids, and
the union of comorbidities flagged as conflicted across that drug's
entries. This mirrors the same "combine multiple label/signal entries into
one per-drug picture" pattern already used elsewhere in this phase
(`context_check.combine_states`, the frontend's `worstConflictState`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.case_analysis import evidence_tier
from app.schemas.case import CandidateChange, CandidateOut

TIER_LABEL = {"high": "HIGH", "moderate": "MODERATE", "low": "LOW", "insufficient": "INSUFFICIENT"}


@dataclass
class _DrugAggregate:
    evidence_score: float = 0.0
    source_ids: set[str] = field(default_factory=set)
    conflicted_comorbidities: set[str] = field(default_factory=set)


def _aggregate_by_drug(candidates: list[CandidateOut]) -> dict[str, _DrugAggregate]:
    aggregates: dict[str, _DrugAggregate] = {}
    for candidate in candidates:
        agg = aggregates.setdefault(candidate.drug, _DrugAggregate())
        agg.evidence_score = max(agg.evidence_score, candidate.evidence_strength_score)
        agg.source_ids.update(e.source_id for e in candidate.primary_condition_evidence)
        agg.conflicted_comorbidities.update(
            c.comorbidity for c in candidate.comorbidity_checks if c.status == "conflict_detected"
        )
    return aggregates


def _build_summary(
    is_new: bool,
    tier_before: str | None,
    tier_after: str,
    new_source_ids: list[str],
    newly_conflicted: list[str],
) -> str:
    parts: list[str] = []
    if is_new:
        parts.append(f"New research candidate detected ({TIER_LABEL[tier_after]} evidence).")
    elif tier_before is not None and tier_before != tier_after:
        parts.append(
            f"Evidence strength changed: {TIER_LABEL[tier_before]} -> {TIER_LABEL[tier_after]}."
        )
    if new_source_ids:
        n = len(new_source_ids)
        parts.append(f"{n} new supporting source{'s' if n != 1 else ''} since last check.")
    if newly_conflicted:
        parts.append(
            "New context conflict(s) detected: "
            + ", ".join(newly_conflicted)
            + " — clinical review required."
        )
    return " ".join(parts)


def diff_candidates(
    snapshot_candidates: list[CandidateOut], current_candidates: list[CandidateOut]
) -> list[CandidateChange]:
    """Returns one CandidateChange per drug that actually changed — a drug
    whose evidence, sources, and conflicts are all identical to the
    snapshot is omitted entirely, so `has_new_evidence = bool(changes)`."""
    snapshot_agg = _aggregate_by_drug(snapshot_candidates)
    current_agg = _aggregate_by_drug(current_candidates)

    changes: list[CandidateChange] = []
    for drug, current in current_agg.items():
        previous = snapshot_agg.get(drug)
        is_new = previous is None

        tier_after = evidence_tier(current.evidence_score)
        tier_before = evidence_tier(previous.evidence_score) if previous else None

        new_source_ids = sorted(
            current.source_ids - (previous.source_ids if previous else set())
        )
        newly_conflicted = sorted(
            current.conflicted_comorbidities
            - (previous.conflicted_comorbidities if previous else set())
        )

        changed = is_new or tier_before != tier_after or new_source_ids or newly_conflicted
        if not changed:
            continue

        changes.append(
            CandidateChange(
                drug=drug,
                is_new_candidate=is_new,
                evidence_tier_before=tier_before,
                evidence_tier_after=tier_after,
                evidence_score_before=previous.evidence_score if previous else None,
                evidence_score_after=current.evidence_score,
                new_supporting_source_ids=new_source_ids,
                newly_conflicted_comorbidities=newly_conflicted,
                summary=_build_summary(is_new, tier_before, tier_after, new_source_ids, newly_conflicted),
            )
        )

    # Highest-signal changes first: new candidates and new conflicts are the
    # most important to see; tier/source-count changes follow.
    changes.sort(
        key=lambda c: (c.is_new_candidate, bool(c.newly_conflicted_comorbidities), c.evidence_score_after),
        reverse=True,
    )
    return changes
