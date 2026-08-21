"""Tests for the CandidateOut contract changes (patient-context plumbing
phase): `disease` is now required (the old empty-string back-compat
default is gone), and the new `patient_context_checks` field defaults to
an empty list since the relevance-checking logic that would populate it
is not implemented yet.
"""
import pytest
from pydantic import ValidationError

from app.schemas.case import (
    CandidateOut,
    CurrentMedicationInteractionNote,
    PatientContextCheck,
)


def _base_kwargs(**overrides):
    kwargs = dict(
        drug="metformin",
        disease="pancreatic cancer",
        research_priority_score=0.5,
        evidence_strength_score=0.5,
        known_indications=[],
        evidence_tier="moderate",
        evidence_tier_reason="1 clinical trial",
        primary_condition_evidence=[],
        comorbidity_checks=[],
        current_medication_interactions=CurrentMedicationInteractionNote(),
        reasoning_trail=["..."],
    )
    kwargs.update(overrides)
    return kwargs


def test_candidate_out_requires_disease():
    kwargs = _base_kwargs()
    del kwargs["disease"]
    with pytest.raises(ValidationError):
        CandidateOut(**kwargs)


def test_candidate_out_accepts_explicit_disease():
    candidate = CandidateOut(**_base_kwargs())
    assert candidate.disease == "pancreatic cancer"


def test_patient_context_checks_defaults_to_empty_list():
    candidate = CandidateOut(**_base_kwargs())
    assert candidate.patient_context_checks == []


def test_patient_context_checks_can_be_supplied():
    check = PatientContextCheck(
        attribute="biomarker:HER2", status="relevance_confirmed", evidence="HER2-positive cohort"
    )
    candidate = CandidateOut(**_base_kwargs(patient_context_checks=[check]))
    assert candidate.patient_context_checks == [check]


def test_patient_context_check_status_is_restricted_to_known_values():
    with pytest.raises(ValidationError):
        PatientContextCheck(attribute="biomarker:HER2", status="not_a_real_status")
