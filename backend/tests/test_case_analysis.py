"""Tests for the case-analysis engine (TheraLens phase): candidate
filtering to the case's primary condition, the three-state comorbidity
check wired end to end, and the research-priority scoring formula. Uses
synthetic Document/ApprovedIndication data (no network) so the suite is
fast and deterministic — the real end-to-end verification against live
openFDA data is documented in PROGRESS.md.
"""
from datetime import date

from app.core.case_analysis import (
    CONFLICT_PENALTY_CAP,
    CONFLICT_PENALTY_PER_HIT,
    INSUFFICIENT_PENALTY_CAP,
    INSUFFICIENT_PENALTY_PER_HIT,
    analyze_case,
)
from app.schemas.document import ApprovedIndication, Document

TODAY = date(2026, 8, 19)


def make_signal_inputs():
    documents = [
        Document(
            drug="metformin",
            disease="stage iv pancreatic cancer",
            source="clinicaltrials",
            source_id="NCT-TEST-0001",
            phase="phase 2",
            date=date(2026, 1, 1),
        )
    ]
    approved = [
        ApprovedIndication(
            drug="metformin",
            disease="type 2 diabetes mellitus",
            source="openfda",
            source_id="LABEL-1",
            contraindications="Contraindicated in severe renal impairment and metabolic acidosis.",
            warnings=None,
        )
    ]
    return documents, approved


def test_candidate_surfaced_for_matching_primary_condition():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=[],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    assert len(candidates) == 1
    assert candidates[0].drug == "metformin"


def test_no_candidates_for_unrelated_primary_condition():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="unrelated disease xyz",
        comorbidities=[],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    assert candidates == []


def test_no_comorbidities_means_no_context_checks_and_score_unchanged():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=[],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    candidate = candidates[0]
    assert candidate.comorbidity_checks == []
    assert candidate.research_priority_score == candidate.evidence_strength_score


def test_conflict_detected_comorbidity_lowers_research_priority_score():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=["renal impairment"],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    candidate = candidates[0]
    check = candidate.comorbidity_checks[0]
    assert check.status == "conflict_detected"
    assert check.evidence is not None
    assert "renal impairment" in check.evidence.lower()

    expected = round(
        max(0.0, candidate.evidence_strength_score - CONFLICT_PENALTY_PER_HIT), 3
    )
    assert candidate.research_priority_score == expected


def test_insufficient_evidence_comorbidity_applies_smaller_penalty():
    documents = [
        Document(
            drug="metformin",
            disease="stage iv pancreatic cancer",
            source="clinicaltrials",
            source_id="NCT-TEST-0001",
            phase="phase 2",
            date=date(2026, 1, 1),
        )
    ]
    approved = [
        ApprovedIndication(
            drug="metformin",
            disease="type 2 diabetes mellitus",
            source="openfda",
            source_id="LABEL-1",
            contraindications=None,
            warnings=None,
        )
    ]
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=["renal impairment"],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    candidate = candidates[0]
    assert candidate.comorbidity_checks[0].status == "insufficient_evidence"

    expected = round(
        max(0.0, candidate.evidence_strength_score - INSUFFICIENT_PENALTY_PER_HIT), 3
    )
    assert candidate.research_priority_score == expected
    # Insufficient-evidence penalty must be smaller than a real conflict's.
    assert INSUFFICIENT_PENALTY_PER_HIT < CONFLICT_PENALTY_PER_HIT


def test_conflict_penalty_caps_with_many_comorbidities():
    documents, approved = make_signal_inputs()
    approved[0].contraindications = (
        "Contraindicated in severe renal impairment, metabolic acidosis, "
        "hepatic failure, cardiac failure, and respiratory failure."
    )
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=[
            "renal impairment",
            "metabolic acidosis",
            "hepatic failure",
            "cardiac failure",
            "respiratory failure",
        ],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    candidate = candidates[0]
    assert all(c.status == "conflict_detected" for c in candidate.comorbidity_checks)
    expected = round(
        max(0.0, candidate.evidence_strength_score - CONFLICT_PENALTY_CAP), 3
    )
    assert candidate.research_priority_score == expected


def test_current_medication_interactions_always_reports_insufficient_data():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=[],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    note = candidates[0].current_medication_interactions
    assert note.status == "insufficient_interaction_data_available"
    assert note.note  # never silently empty


def test_research_priority_score_never_goes_negative():
    documents, approved = make_signal_inputs()
    approved[0].contraindications = "renal impairment metabolic acidosis " * 20
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=["renal impairment", "metabolic acidosis"] * 10,
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    assert candidates[0].research_priority_score >= 0.0


def test_reasoning_trail_is_non_prescriptive_and_populated():
    documents, approved = make_signal_inputs()
    candidates = analyze_case(
        primary_condition="pancreatic cancer",
        comorbidities=["renal impairment"],
        documents=documents,
        approved=approved,
        today=TODAY,
    )
    trail = candidates[0].reasoning_trail
    assert len(trail) >= 4
    joined = " ".join(trail).lower()
    assert "take metformin" not in joined
    assert "best treatment" not in joined
    assert "clinical review required" in joined
