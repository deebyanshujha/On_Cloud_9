"""Tests the persistent known-drugs cache (Step 10): different surface
forms of the same drug merge into one row instead of creating duplicates,
and the cache accumulates across calls rather than being reset."""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingestion.store import load_all_known_drugs, upsert_known_drug
from app.models.db import Base
from app.models.known_drug import KnownDrugRecord


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


def test_upsert_known_drug_creates_new_entry():
    session = make_session()
    canonical = upsert_known_drug(session, "metformin", resolve_rxnorm=False)
    assert canonical == "metformin"
    assert load_all_known_drugs(session) == ["metformin"]


def test_upsert_known_drug_merges_surface_form_variants():
    session = make_session()
    upsert_known_drug(session, "Metformin", resolve_rxnorm=False)
    upsert_known_drug(session, "Metformin Hydrochloride 500mg", resolve_rxnorm=False)
    upsert_known_drug(session, "metformin hcl tablet", resolve_rxnorm=False)

    drugs = load_all_known_drugs(session)
    assert drugs == ["metformin"]

    record = session.query(KnownDrugRecord).one()
    variants = json.loads(record.name_variants)
    assert "Metformin" in variants
    assert "Metformin Hydrochloride 500mg" in variants
    assert "metformin hcl tablet" in variants


def test_upsert_known_drug_accumulates_distinct_drugs():
    session = make_session()
    upsert_known_drug(session, "metformin", resolve_rxnorm=False)
    upsert_known_drug(session, "sildenafil", resolve_rxnorm=False)

    assert set(load_all_known_drugs(session)) == {"metformin", "sildenafil"}


def test_cache_persists_across_separate_calls_not_reset():
    session = make_session()
    upsert_known_drug(session, "metformin", resolve_rxnorm=False)
    assert load_all_known_drugs(session) == ["metformin"]

    upsert_known_drug(session, "sildenafil", resolve_rxnorm=False)
    assert set(load_all_known_drugs(session)) == {"metformin", "sildenafil"}
