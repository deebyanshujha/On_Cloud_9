"""Tests for Case storage (TheraLens phase): dynamic free-text case
creation (no hardcoded disease/drug lists — any string is accepted and
normalized the same way every other disease/drug mention already is),
retrieval, saved-flag updates, and analysis-result persistence.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingestion.store import (
    create_case,
    get_case,
    get_case_conditions,
    get_case_medications,
    load_case_analysis,
    save_case_analysis,
    set_case_saved,
)
from app.models.db import Base


def make_session():
    engine = create_engine("sqlite:///:memory:")
    from app.models import case  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_create_case_with_arbitrary_dynamic_condition_and_medication_input():
    # Deliberately not a "known" disease/drug from any fixture — proves
    # there's no hardcoded allowlist gatekeeping case creation.
    session = make_session()
    case = create_case(
        session,
        primary_condition="Glorbnitis Syndrome Type IX",
        comorbidities=["Zephyrian Fever", "Blorptic Neuropathy"],
        current_medications=["Quixotane 50mg", "Fablutrex XR"],
    )

    assert case.id is not None
    assert case.primary_condition == "glorbnitis syndrome type ix"
    assert case.saved is False

    conditions = get_case_conditions(session, case.id)
    assert "zephyrian fever" in conditions
    assert "blorptic neuropathy" in conditions

    medications = get_case_medications(session, case.id)
    # normalize_drug_name strips dosage tokens like "50mg"
    assert "quixotane" in medications
    assert "fablutrex xr" in medications or "fablutrex" in medications


def test_create_case_with_no_comorbidities_or_medications():
    session = make_session()
    case = create_case(session, primary_condition="some condition", comorbidities=[], current_medications=[])
    assert get_case_conditions(session, case.id) == []
    assert get_case_medications(session, case.id) == []


def test_create_case_skips_blank_entries():
    session = make_session()
    case = create_case(
        session,
        primary_condition="condition x",
        comorbidities=["", "   ", "real comorbidity"],
        current_medications=[""],
    )
    assert get_case_conditions(session, case.id) == ["real comorbidity"]
    assert get_case_medications(session, case.id) == []


def test_get_case_returns_none_for_unknown_id():
    session = make_session()
    assert get_case(session, 999) is None


def test_set_case_saved_flips_flag():
    session = make_session()
    case = create_case(session, primary_condition="x", comorbidities=[], current_medications=[])
    assert case.saved is False

    updated = set_case_saved(session, case.id, True)
    assert updated.saved is True

    refetched = get_case(session, case.id)
    assert refetched.saved is True


def test_set_case_saved_returns_none_for_unknown_id():
    session = make_session()
    assert set_case_saved(session, 999, True) is None


def test_save_and_load_case_analysis_overwrites_not_appends():
    session = make_session()
    case = create_case(session, primary_condition="x", comorbidities=[], current_medications=[])

    assert load_case_analysis(session, case.id) is None

    save_case_analysis(session, case.id, '{"candidates": []}')
    first = load_case_analysis(session, case.id)
    assert first.result_json == '{"candidates": []}'

    save_case_analysis(session, case.id, '{"candidates": [1]}')
    second = load_case_analysis(session, case.id)
    assert second.result_json == '{"candidates": [1]}'
    # Overwritten in place, not a second row.
    assert first.id == second.id
