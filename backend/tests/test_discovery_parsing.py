"""Tests for discovery-mode parsing (Step 10): extracting drug names FROM
results instead of requiring a caller-supplied drug, for both
ClinicalTrials.gov and Europe PMC (bioRxiv/medRxiv)."""
from datetime import date

from app.ingestion.biorxiv import extract_drugs, parse_preprint_to_documents_discovery
from app.ingestion.clinicaltrials import (
    extract_drug_names,
    parse_study_to_documents_discovery,
)
from tests.test_biorxiv import FakeNerModel, _FakeEntity

BROAD_STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT09999999"},
        "statusModule": {
            "startDateStruct": {"date": "2026-06-01"},
            "studyFirstPostDateStruct": {"date": "2026-07-01"},
        },
        "conditionsModule": {"conditions": ["Pancreatic Cancer"]},
        "designModule": {"phases": ["PHASE2"]},
        "armsInterventionsModule": {
            "interventions": [
                {"type": "DRUG", "name": "Metformin"},
                {"type": "DEVICE", "name": "Sham Device"},
            ]
        },
    }
}


def test_extract_drug_names_filters_to_drug_type_only():
    assert extract_drug_names(BROAD_STUDY) == ["metformin"]


def test_extract_drug_names_normalizes_and_dedupes():
    study = {
        "protocolSection": {
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "DRUG", "name": "Dose reduction of lezertinib"},
                    {"type": "DRUG", "name": "Lezertinib"},
                ]
            }
        }
    }
    assert extract_drug_names(study) == ["lezertinib"]


def test_parse_study_to_documents_discovery_pairs_every_drug_with_every_condition():
    docs = parse_study_to_documents_discovery(BROAD_STUDY)
    assert len(docs) == 1
    assert docs[0].drug == "metformin"
    assert docs[0].disease == "Pancreatic Cancer"
    assert docs[0].date == date(2026, 7, 1)


def test_parse_study_to_documents_discovery_no_drug_interventions_returns_empty():
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001"},
            "statusModule": {},
            "conditionsModule": {"conditions": ["Migraine"]},
            "designModule": {},
            "armsInterventionsModule": {
                "interventions": [{"type": "DEVICE", "name": "Neurostim"}]
            },
        }
    }
    assert parse_study_to_documents_discovery(study) == []


def test_extract_drugs_filters_to_chemical_label_and_dedupes():
    text = "some text"
    nlp = FakeNerModel(
        {
            text: [
                _FakeEntity("Metformin", "CHEMICAL"),
                _FakeEntity("metformin", "CHEMICAL"),  # duplicate, different case
                _FakeEntity("Pancreatic Cancer", "DISEASE"),
            ]
        }
    )
    assert extract_drugs(nlp, text) == ["metformin"]


def test_parse_preprint_to_documents_discovery_pairs_every_drug_with_every_disease():
    doc_text = "Title. Abstract."
    nlp = FakeNerModel(
        {
            doc_text: [
                _FakeEntity("metformin", "CHEMICAL"),
                _FakeEntity("pancreatic cancer", "DISEASE"),
            ]
        }
    )
    paper = {
        "doi": "10.1101/2026.01.01.000001",
        "title": "Title",
        "abstractText": "Abstract.",
        "firstPublicationDate": "2026-01-15",
        "bookOrReportDetails": {"publisher": "bioRxiv"},
    }

    docs = parse_preprint_to_documents_discovery(paper, nlp=nlp)

    assert len(docs) == 1
    assert docs[0].drug == "metformin"
    assert docs[0].disease == "pancreatic cancer"


def test_parse_preprint_to_documents_discovery_no_drug_entities_returns_empty():
    doc_text = "Title. Abstract."
    nlp = FakeNerModel({doc_text: [_FakeEntity("pancreatic cancer", "DISEASE")]})
    paper = {
        "doi": "10.1101/2026.01.01.000002",
        "title": "Title",
        "abstractText": "Abstract.",
        "firstPublicationDate": "2026-01-15",
        "bookOrReportDetails": {"publisher": "bioRxiv"},
    }
    assert parse_preprint_to_documents_discovery(paper, nlp=nlp) == []
