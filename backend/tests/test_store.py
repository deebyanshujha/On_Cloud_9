"""Tests the storage layer (app/ingestion/store.py): inserting Documents and
ApprovedIndications, skipping duplicates on re-run, and reading them back
out."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingestion.store import (
    load_all_approved_indications,
    load_all_documents,
    upsert_approved_indications,
    upsert_documents,
)
from app.models.db import Base
from app.schemas.document import ApprovedIndication, Document


def make_session():
    engine = create_engine("sqlite:///:memory:")
    from app.models import approved_indication, document  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_upsert_inserts_new_documents():
    session = make_session()
    docs = [
        Document(
            drug="metformin",
            disease="pancreatic cancer",
            source="clinicaltrials",
            source_id="NCT-TEST-0001",
            phase="phase 2",
            date=date(2025, 1, 1),
            url="https://clinicaltrials.gov/study/NCT-TEST-0001",
        )
    ]

    inserted, skipped = upsert_documents(session, docs)

    assert inserted == 1
    assert skipped == 0
    assert len(load_all_documents(session)) == 1


def test_upsert_skips_exact_duplicates_on_rerun():
    session = make_session()
    docs = [
        Document(
            drug="metformin",
            disease="pancreatic cancer",
            source="clinicaltrials",
            source_id="NCT-TEST-0001",
            phase="phase 2",
            date=date(2025, 1, 1),
            url="https://clinicaltrials.gov/study/NCT-TEST-0001",
        )
    ]

    upsert_documents(session, docs)
    inserted, skipped = upsert_documents(session, docs)

    assert inserted == 0
    assert skipped == 1
    assert len(load_all_documents(session)) == 1


def test_upsert_normalizes_drug_and_disease_case():
    session = make_session()
    docs = [
        Document(
            drug="Metformin",
            disease="Pancreatic Cancer",
            source="clinicaltrials",
            source_id="NCT-TEST-0002",
            date=date(2025, 1, 1),
        )
    ]

    upsert_documents(session, docs)
    stored = load_all_documents(session)

    assert stored[0].drug == "metformin"
    assert stored[0].disease == "pancreatic cancer"


def test_upsert_inserts_new_approved_indications():
    session = make_session()
    indications = [
        ApprovedIndication(
            drug="metformin",
            disease="type 2 diabetes mellitus",
            source="openfda",
            source_id="LABEL-TEST-0001",
            url="https://api.fda.gov/drug/label.json?search=id:%22LABEL-TEST-0001%22",
        )
    ]

    inserted, skipped = upsert_approved_indications(session, indications)

    assert inserted == 1
    assert skipped == 0
    assert len(load_all_approved_indications(session)) == 1


def test_upsert_skips_exact_duplicate_approved_indications_on_rerun():
    session = make_session()
    indications = [
        ApprovedIndication(
            drug="metformin",
            disease="type 2 diabetes mellitus",
            source="openfda",
            source_id="LABEL-TEST-0001",
        )
    ]

    upsert_approved_indications(session, indications)
    inserted, skipped = upsert_approved_indications(session, indications)

    assert inserted == 0
    assert skipped == 1
    assert len(load_all_approved_indications(session)) == 1


def test_upsert_normalizes_approved_indication_drug_and_disease_case():
    session = make_session()
    indications = [
        ApprovedIndication(
            drug="Metformin",
            disease="Type 2 Diabetes Mellitus",
            source="openfda",
            source_id="LABEL-TEST-0002",
        )
    ]

    upsert_approved_indications(session, indications)
    stored = load_all_approved_indications(session)

    assert stored[0].drug == "metformin"
    assert stored[0].disease == "type 2 diabetes mellitus"
