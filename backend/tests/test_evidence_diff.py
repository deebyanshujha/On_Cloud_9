"""Tests for the Phase 3 evidence-diff engine (app/core/evidence_diff.py):
detecting tier/score changes, new supporting sources, new context conflicts,
and brand-new candidates between a case's saved snapshot and a fresh
re-analysis. Uses synthetic CandidateOut objects (no network/DB) so the
suite is fast and deterministic.
"""
from app.core.evidence_diff import diff_candidates
from app.schemas.case import (
    CandidateOut,
    ComorbidityCheck,
    CurrentMedicationInteractionNote,
    SupportingEvidence,
)


def make_candidate(
    drug: str,
    score: float,
    source_ids: list[str],
    comorbidity_checks: list[ComorbidityCheck] | None = None,
) -> CandidateOut:
    return CandidateOut(
        drug=drug,
        research_priority_score=score,
        evidence_strength_score=score,
        known_indications=[],
        primary_condition_evidence=[
            SupportingEvidence(source="clinicaltrials", source_id=sid, url=None, date=None, phase=None)
            for sid in source_ids
        ],
        comorbidity_checks=comorbidity_checks or [],
        current_medication_interactions=CurrentMedicationInteractionNote(),
        reasoning_trail=["..."],
    )


def test_no_change_produces_no_diff():
    snapshot = [make_candidate("metformin", 0.5, ["NCT001"])]
    current = [make_candidate("metformin", 0.5, ["NCT001"])]
    assert diff_candidates(snapshot, current) == []


def test_tier_change_is_detected():
    snapshot = [make_candidate("metformin", 0.5, ["NCT001"])]  # moderate
    current = [make_candidate("metformin", 0.8, ["NCT001"])]  # high
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    change = changes[0]
    assert change.drug == "metformin"
    assert change.is_new_candidate is False
    assert change.evidence_tier_before == "moderate"
    assert change.evidence_tier_after == "high"
    assert "MODERATE -> HIGH" in change.summary


def test_new_supporting_source_is_detected_even_without_tier_change():
    snapshot = [make_candidate("metformin", 0.5, ["NCT001"])]
    current = [make_candidate("metformin", 0.5, ["NCT001", "NCT002"])]
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    assert changes[0].new_supporting_source_ids == ["NCT002"]
    assert "1 new supporting source" in changes[0].summary


def test_new_context_conflict_is_detected():
    snapshot = [
        make_candidate(
            "metformin",
            0.5,
            ["NCT001"],
            [ComorbidityCheck(comorbidity="renal impairment", status="no_conflict_detected", evidence=None)],
        )
    ]
    current = [
        make_candidate(
            "metformin",
            0.5,
            ["NCT001"],
            [ComorbidityCheck(comorbidity="renal impairment", status="conflict_detected", evidence="some text")],
        )
    ]
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    assert changes[0].newly_conflicted_comorbidities == ["renal impairment"]
    assert "clinical review required" in changes[0].summary


def test_brand_new_candidate_is_detected():
    snapshot = [make_candidate("metformin", 0.5, ["NCT001"])]
    current = [
        make_candidate("metformin", 0.5, ["NCT001"]),
        make_candidate("sildenafil", 0.6, ["NCT099"]),
    ]
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    change = changes[0]
    assert change.drug == "sildenafil"
    assert change.is_new_candidate is True
    assert change.evidence_tier_before is None
    assert change.evidence_score_before is None
    assert "New research candidate detected" in change.summary


def test_multiple_signals_for_same_drug_are_aggregated_by_max_score_and_union_sources():
    # analyze_case can produce more than one CandidateOut per drug (one per
    # matched disease-text variant) — the diff must treat them as one drug.
    snapshot = [
        make_candidate("metformin", 0.3, ["NCT001"]),
        make_candidate("metformin", 0.5, ["NCT002"]),
    ]
    current = [
        make_candidate("metformin", 0.3, ["NCT001"]),
        make_candidate("metformin", 0.5, ["NCT002", "NCT003"]),
    ]
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    assert changes[0].new_supporting_source_ids == ["NCT003"]
    # aggregate score (max=0.5) unchanged -> no tier change reported
    assert changes[0].evidence_tier_before == changes[0].evidence_tier_after


def test_score_decrease_is_also_reported_not_only_increases():
    snapshot = [make_candidate("metformin", 0.8, ["NCT001"])]  # high
    current = [make_candidate("metformin", 0.2, ["NCT001"])]  # low
    changes = diff_candidates(snapshot, current)
    assert len(changes) == 1
    assert changes[0].evidence_tier_before == "high"
    assert changes[0].evidence_tier_after == "low"


def test_empty_snapshot_and_current_produces_no_diff():
    assert diff_candidates([], []) == []


def test_new_candidates_and_conflicts_sort_before_plain_tier_changes():
    snapshot = [make_candidate("drug_a", 0.5, ["NCT001"])]
    current = [
        make_candidate("drug_a", 0.9, ["NCT001"]),  # tier change only
        make_candidate("drug_b", 0.4, ["NCT002"]),  # brand new
    ]
    changes = diff_candidates(snapshot, current)
    assert changes[0].drug == "drug_b"
    assert changes[0].is_new_candidate is True
