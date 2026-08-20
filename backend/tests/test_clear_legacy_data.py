"""Tests scripts/clear_legacy_bulk_data.py's legacy-row detection logic
against an isolated in-memory DB — never touches the real arbitrage.db."""
from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base
from app.models.document import DocumentRecord
from app.models.known_drug import KnownDrugRecord
from scripts.clear_legacy_bulk_data import find_legacy_document_ids, per_drug_counts


def make_session():
    engine = create_engine("sqlite:///:memory:")
    from app.models import (  # noqa: F401  (registers the tables)
        approved_indication,
        document,
        ingestion_status,
        known_drug,
    )

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _add_document(session, drug, disease="some disease", source="clinicaltrials", source_id="NCT1"):
    doc = DocumentRecord(
        drug=drug, disease=disease, source=source, source_id=source_id,
        phase=None, date=date(2026, 1, 1), url=None, num_mentions=1,
    )
    session.add(doc)
    session.flush()
    return doc


def test_legacy_drug_with_no_known_drugs_row_is_flagged():
    session = make_session()
    _add_document(session, "metformin", source_id="NCT1")
    _add_document(session, "metformin", source_id="NCT2")

    legacy_ids = find_legacy_document_ids(session)
    assert len(legacy_ids) == 2


def test_discovered_drug_with_known_drugs_row_is_not_flagged():
    session = make_session()
    session.add(KnownDrugRecord(canonical_name="lezertinib"))
    session.flush()
    _add_document(session, "dose reduction of lezertinib", source_id="NCT1")

    # normalize_drug_name strips the "dose reduction of" filler, so this
    # should resolve to the known_drugs canonical name and NOT be legacy.
    legacy_ids = find_legacy_document_ids(session)
    assert legacy_ids == []


def test_mixed_legacy_and_discovered_drugs():
    session = make_session()
    session.add(KnownDrugRecord(canonical_name="aspirin"))
    session.flush()
    legacy_doc = _add_document(session, "metformin", source_id="NCT1")
    _add_document(session, "aspirin", source_id="NCT2")

    legacy_ids = find_legacy_document_ids(session)
    assert legacy_ids == [legacy_doc.id]


def test_per_drug_counts():
    session = make_session()
    _add_document(session, "metformin", source_id="NCT1")
    _add_document(session, "metformin", source_id="NCT2")
    _add_document(session, "aspirin", source_id="NCT3")

    counts = per_drug_counts(session)
    assert counts["metformin"] == 2
    assert counts["aspirin"] == 1


def test_no_legacy_rows_when_all_drugs_known():
    session = make_session()
    session.add(KnownDrugRecord(canonical_name="metformin"))
    session.flush()
    _add_document(session, "metformin", source_id="NCT1")

    assert find_legacy_document_ids(session) == []
