"""Tests scripts/clean_junk_medications.py's junk-row detection logic
against an isolated in-memory DB — never touches the real arbitrage.db."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.case import CaseMedicationRecord, CaseRecord
from app.models.db import Base
from app.models.document import DocumentRecord
from app.models.known_drug import KnownDrugRecord
from scripts.clean_junk_medications import (
    find_junk_case_medication_ids,
    find_junk_document_ids,
    find_junk_known_drug_ids,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    from app.models import (  # noqa: F401  (registers the tables)
        approved_indication,
        case,
        document,
        ingestion_status,
        known_drug,
    )

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _add_document(session, drug, source_id):
    doc = DocumentRecord(
        drug=drug, disease="some disease", source="clinicaltrials", source_id=source_id,
        phase=None, date=None, url=None, num_mentions=1,
    )
    session.add(doc)
    session.flush()
    return doc


def test_placebo_documents_are_flagged():
    session = make_session()
    junk = _add_document(session, "placebo", "NCT1")
    real = _add_document(session, "metformin", "NCT2")

    ids = find_junk_document_ids(session)
    assert ids == [junk.id]
    assert real.id not in ids


def test_no_junk_documents_when_all_clean():
    session = make_session()
    _add_document(session, "metformin", "NCT1")
    _add_document(session, "sildenafil", "NCT2")

    assert find_junk_document_ids(session) == []


def test_junk_known_drug_rows_are_flagged():
    session = make_session()
    junk = KnownDrugRecord(canonical_name="placebo comparator")
    real = KnownDrugRecord(canonical_name="metformin")
    session.add_all([junk, real])
    session.flush()

    ids = find_junk_known_drug_ids(session)
    assert ids == [junk.id]


def test_junk_case_medication_rows_are_flagged():
    session = make_session()
    case = CaseRecord(primary_condition="some disease")
    session.add(case)
    session.flush()
    junk = CaseMedicationRecord(case_id=case.id, name="surgery")
    real = CaseMedicationRecord(case_id=case.id, name="metformin")
    session.add_all([junk, real])
    session.flush()

    ids = find_junk_case_medication_ids(session)
    assert ids == [junk.id]
