"""Tests for ClinicalTrials.gov parsing logic (Step 3). These use a
hand-crafted sample of the raw API shape so they don't depend on network
access or on ClinicalTrials.gov's live data.
"""
from datetime import date

from app.ingestion.clinicaltrials import (
    normalize_phase,
    parse_ctgov_date,
    parse_study_to_documents,
)

SAMPLE_STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT00359762"},
        "statusModule": {
            "startDateStruct": {"date": "2006-09"},
            "studyFirstPostDateStruct": {"date": "2006-08-02"},
        },
        "conditionsModule": {"conditions": ["Type 2 Diabetes Mellitus"]},
        "designModule": {"phases": ["PHASE3"]},
    }
}

MULTI_CONDITION_STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT04947020"},
        "statusModule": {
            "startDateStruct": {"date": "2021-08-01"},
            "studyFirstPostDateStruct": {"date": "2021-07-01"},
        },
        "conditionsModule": {"conditions": ["Rectal Cancer", "Overall Survival"]},
        "designModule": {},
    }
}


def test_normalize_phase_picks_highest():
    assert normalize_phase(["PHASE2", "PHASE3"]) == "phase 3"


def test_normalize_phase_handles_na():
    assert normalize_phase(["NA"]) == "not applicable"


def test_normalize_phase_handles_none():
    assert normalize_phase(None) is None
    assert normalize_phase([]) is None


def test_parse_ctgov_date_full():
    assert parse_ctgov_date("2018-03-29") == date(2018, 3, 29)


def test_parse_ctgov_date_year_month_only():
    assert parse_ctgov_date("2006-09") == date(2006, 9, 1)


def test_parse_ctgov_date_year_only():
    assert parse_ctgov_date("2006") == date(2006, 1, 1)


def test_parse_ctgov_date_none():
    assert parse_ctgov_date(None) is None


def test_parse_study_to_documents_basic_fields():
    docs = parse_study_to_documents(SAMPLE_STUDY, queried_drug="metformin")

    assert len(docs) == 1
    doc = docs[0]
    assert doc.drug == "metformin"
    assert doc.disease == "Type 2 Diabetes Mellitus"
    assert doc.source == "clinicaltrials"
    assert doc.source_id == "NCT00359762"
    assert doc.phase == "phase 3"
    assert doc.date == date(2006, 8, 2)
    assert doc.url == "https://clinicaltrials.gov/study/NCT00359762"


def test_parse_study_to_documents_one_per_condition():
    docs = parse_study_to_documents(MULTI_CONDITION_STUDY, queried_drug="metformin")

    assert len(docs) == 2
    diseases = {d.disease for d in docs}
    assert diseases == {"Rectal Cancer", "Overall Survival"}
    assert all(d.phase is None for d in docs)


def test_parse_study_to_documents_missing_nct_id_returns_empty():
    broken_study = {"protocolSection": {"identificationModule": {}}}
    assert parse_study_to_documents(broken_study, queried_drug="metformin") == []


def test_parse_study_to_documents_missing_conditions_returns_empty():
    no_conditions_study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT99999999"},
            "statusModule": {},
            "conditionsModule": {"conditions": []},
            "designModule": {},
        }
    }
    assert parse_study_to_documents(no_conditions_study, queried_drug="metformin") == []
