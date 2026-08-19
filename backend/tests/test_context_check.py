"""Tests for the comorbidity-vs-drug-label context check (TheraLens phase).
Uses real openFDA label text (metformin's actual CONTRAINDICATIONS section,
pulled live and verified 2026-08-19) rather than fabricated text, per the
project's no-fabrication rule — see app/core/context_check.py.
"""
from app.core.context_check import check_comorbidity_conflict, combine_states

# Real openFDA contraindications text for metformin hydrochloride tablets
# (label id 19e4bfb8-2ed1-4a6b-adf5-853ad2953362), pulled live 2026-08-19.
REAL_METFORMIN_CONTRAINDICATIONS = (
    "4 CONTRAINDICATIONS Metformin hydrochloride tablets are contraindicated "
    "in patients with: Severe renal impairment (eGFR below 30 mL/min/1.73 "
    "m 2 ) [ see Warnings and Precautions (5.1) ]. Hypersensitivity to "
    "metformin. Acute or chronic metabolic acidosis, including diabetic "
    "ketoacidosis, with or without coma."
)

# Real openFDA indications_and_usage text used as a stand-in "warnings"-style
# field with no overlap with the comorbidity under test, for a genuine
# no-conflict case.
REAL_METFORMIN_INDICATIONS_TEXT = (
    "Metformin hydrochloride tablets are indicated as an adjunct to diet "
    "and exercise to improve glycemic control in adults with type 2 "
    "diabetes mellitus."
)


def test_conflict_detected_against_real_known_contraindication():
    state, evidence = check_comorbidity_conflict(
        "renal impairment", REAL_METFORMIN_CONTRAINDICATIONS, None
    )
    assert state == "conflict_detected"
    assert evidence is not None
    # Evidence must be verbatim real label text, not fabricated.
    assert evidence in REAL_METFORMIN_CONTRAINDICATIONS
    assert "renal" in evidence.lower()


def test_conflict_detected_against_metabolic_acidosis():
    state, evidence = check_comorbidity_conflict(
        "metabolic acidosis", REAL_METFORMIN_CONTRAINDICATIONS, None
    )
    assert state == "conflict_detected"
    assert evidence is not None
    assert evidence in REAL_METFORMIN_CONTRAINDICATIONS


def test_no_conflict_detected_when_label_text_present_but_silent():
    state, evidence = check_comorbidity_conflict(
        "asthma", REAL_METFORMIN_CONTRAINDICATIONS, None
    )
    assert state == "no_conflict_detected"
    assert evidence is None


def test_insufficient_evidence_when_no_label_text_at_all():
    state, evidence = check_comorbidity_conflict("renal impairment", None, None)
    assert state == "insufficient_evidence"
    assert evidence is None


def test_insufficient_evidence_for_bare_generic_comorbidity_term():
    # Same single-token-genericity guard already used for indications
    # matching (app.core.disease_matching.is_too_generic_to_match) applies
    # here too — "disease" alone is too vague to trust.
    state, evidence = check_comorbidity_conflict(
        "disease", REAL_METFORMIN_CONTRAINDICATIONS, None
    )
    assert state == "insufficient_evidence"
    assert evidence is None


def test_checks_warnings_field_too():
    state, evidence = check_comorbidity_conflict(
        "renal impairment", None, REAL_METFORMIN_CONTRAINDICATIONS
    )
    assert state == "conflict_detected"
    assert evidence is not None


def test_combine_states_conflict_wins_over_no_conflict():
    results = [("no_conflict_detected", None), ("conflict_detected", "some evidence")]
    state, evidence = combine_states(results)
    assert state == "conflict_detected"
    assert evidence == "some evidence"


def test_combine_states_no_conflict_wins_over_insufficient():
    results = [("insufficient_evidence", None), ("no_conflict_detected", None)]
    state, evidence = combine_states(results)
    assert state == "no_conflict_detected"


def test_combine_states_empty_list_is_insufficient_evidence():
    state, evidence = combine_states([])
    assert state == "insufficient_evidence"
    assert evidence is None
