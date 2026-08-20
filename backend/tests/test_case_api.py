"""Tests for the /cases API endpoints (TheraLens phase). The case endpoints
read/write the DB directly per-request (unlike /signals, which snapshots
into app.state once at startup), so each test points app.main at a fresh
temporary SQLite file — fully isolated from backend/data/arbitrage.db —
via monkeypatch.setattr rather than touching the real database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.core.runtime_research import RuntimeResearchResult
from app.models.db import Base
from app.schemas.case import ResearchMetadata


def _fake_runtime_research(
    session,
    *,
    case_id,
    primary_condition,
    comorbidities,
    current_medications,
    local_approved,
    local_documents=None,
):
    """No-network stand-in for run_runtime_case_research used by the
    `client` fixture below. Real Europe PMC/PubMed/ClinicalTrials.gov calls
    have no place in this offline unit-test suite (they were previously
    hanging the whole suite until the httpx timeout) — case-analysis tests
    instead seed local documents/approved indications directly and this
    stub hands them straight through as if they were the live-fetched
    result, mirroring (without the network-bound RxNorm validation calls)
    the real function's local-fallback behavior. Tests that need to
    exercise runtime research's own retrieval/validation/fallback logic
    live in tests/test_runtime_research.py with the HTTP fetchers mocked."""
    return RuntimeResearchResult(
        documents=list(local_documents or []),
        approved_indications=list(local_approved),
        metadata=ResearchMetadata(),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_cases.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    test_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def fake_init_db() -> None:
        from app.models import case, document  # noqa: F401  (registers tables)
        from app.models import approved_indication, ingestion_status, known_drug  # noqa: F401

        Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(main_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(main_module, "init_db", fake_init_db)
    monkeypatch.setattr(main_module, "run_runtime_case_research", _fake_runtime_research)

    return TestClient(main_module.app)


def test_list_cases_empty_initially(client):
    response = client.get("/cases")
    assert response.status_code == 200
    assert response.json() == []


def test_list_cases_returns_created_cases_newest_first(client):
    first = client.post(
        "/cases", json={"primary_condition": "condition a", "comorbidities": [], "current_medications": []}
    ).json()
    second = client.post(
        "/cases", json={"primary_condition": "condition b", "comorbidities": [], "current_medications": []}
    ).json()

    response = client.get("/cases")
    assert response.status_code == 200
    ids = [c["id"] for c in response.json()]
    assert ids == [second["id"], first["id"]]


def test_list_cases_summarizes_last_analysis(client):
    created = client.post(
        "/cases", json={"primary_condition": "x", "comorbidities": [], "current_medications": []}
    ).json()

    before_analysis = next(c for c in client.get("/cases").json() if c["id"] == created["id"])
    assert before_analysis["candidate_count"] is None
    assert before_analysis["conflict_count"] is None

    client.post(f"/cases/{created['id']}/analyze")

    after_analysis = next(c for c in client.get("/cases").json() if c["id"] == created["id"])
    assert after_analysis["candidate_count"] == 0
    assert after_analysis["conflict_count"] == 0
    assert after_analysis["last_analyzed_at"] is not None


def test_create_case_with_dynamic_free_text_input(client):
    response = client.post(
        "/cases",
        json={
            "primary_condition": "Novel Condition Alpha",
            "comorbidities": ["Made Up Comorbidity"],
            "current_medications": ["Fictional Drug 10mg"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["primary_condition"] == "novel condition alpha"
    assert body["comorbidities"] == ["made up comorbidity"]
    assert body["current_medications"] == ["fictional drug"]
    assert body["saved"] is False


def test_get_case_returns_case_and_null_analysis_before_analyze(client):
    created = client.post(
        "/cases", json={"primary_condition": "x", "comorbidities": [], "current_medications": []}
    ).json()

    response = client.get(f"/cases/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["case"]["id"] == created["id"]
    assert body["last_analysis"] is None


def test_get_unknown_case_returns_404(client):
    response = client.get("/cases/999999")
    assert response.status_code == 404


def test_patch_case_marks_saved(client):
    created = client.post(
        "/cases", json={"primary_condition": "x", "comorbidities": [], "current_medications": []}
    ).json()

    response = client.patch(f"/cases/{created['id']}", json={"saved": True})
    assert response.status_code == 200
    assert response.json()["saved"] is True

    refetched = client.get(f"/cases/{created['id']}").json()
    assert refetched["case"]["saved"] is True


def test_patch_unknown_case_returns_404(client):
    response = client.patch("/cases/999999", json={"saved": True})
    assert response.status_code == 404


def test_analyze_case_with_no_matching_evidence_returns_empty_candidates(client):
    created = client.post(
        "/cases",
        json={
            "primary_condition": "Completely Fictional Disease Zzyzx",
            "comorbidities": [],
            "current_medications": [],
        },
    ).json()

    response = client.post(f"/cases/{created['id']}/analyze")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == created["id"]
    assert body["candidates"] == []


def test_analyze_case_persists_last_analysis_result(client):
    created = client.post(
        "/cases",
        json={"primary_condition": "some disease", "comorbidities": [], "current_medications": []},
    ).json()

    analyze_response = client.post(f"/cases/{created['id']}/analyze")
    assert analyze_response.status_code == 200

    fetched = client.get(f"/cases/{created['id']}").json()
    assert fetched["last_analysis"] is not None
    assert fetched["last_analysis"]["case_id"] == created["id"]


def test_analyze_unknown_case_returns_404(client):
    response = client.post("/cases/999999/analyze")
    assert response.status_code == 404


def test_analyze_surfaces_real_candidate_with_comorbidity_conflict(client, monkeypatch):
    """End-to-end with real ingested data: seeds the temp DB with the exact
    documents/approved-indications shape produced by the real pipeline
    (metformin/pancreatic cancer signal + metformin's real, verified
    openFDA contraindications text), then confirms the case-analysis
    engine surfaces it with a correctly-detected conflict."""
    from app.ingestion.store import upsert_approved_indications, upsert_documents
    from app.schemas.document import ApprovedIndication, Document
    from datetime import date

    main_module.init_db()  # creates tables on the fixture's temp engine
    session = main_module.SessionLocal()
    upsert_documents(
        session,
        [
            Document(
                drug="metformin",
                disease="stage iv pancreatic cancer",
                source="clinicaltrials",
                source_id="NCT-TEST-9999",
                phase="phase 2",
                date=date(2026, 1, 1),
            )
        ],
    )
    upsert_approved_indications(
        session,
        [
            ApprovedIndication(
                drug="metformin",
                disease="type 2 diabetes mellitus",
                source="openfda",
                source_id="LABEL-TEST-9999",
                contraindications=(
                    "4 CONTRAINDICATIONS Metformin hydrochloride tablets are "
                    "contraindicated in patients with: Severe renal impairment "
                    "(eGFR below 30 mL/min/1.73 m 2 )."
                ),
            )
        ],
    )
    session.close()

    created = client.post(
        "/cases",
        json={
            "primary_condition": "pancreatic cancer",
            "comorbidities": ["renal impairment"],
            "current_medications": [],
        },
    ).json()

    response = client.post(f"/cases/{created['id']}/analyze")
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["drug"] == "metformin"
    check = candidate["comorbidity_checks"][0]
    assert check["status"] == "conflict_detected"
    assert "renal impairment" in check["evidence"].lower()
    assert candidate["research_priority_score"] < candidate["evidence_strength_score"]


# --- Phase 3: saved-case snapshot + "re-check for new evidence" ------------


def _seed_pancreatic_cancer_data(source_id: str = "NCT-TEST-0001"):
    """Seeds via main_module.SessionLocal (the fixture's temp-DB engine,
    monkeypatched in by the `client` fixture) — NOT `app.models.db.
    SessionLocal` directly, which would bind to the real production
    arbitrage.db and pollute it with test rows."""
    from datetime import date

    from app.ingestion.store import upsert_approved_indications, upsert_documents
    from app.schemas.document import ApprovedIndication, Document

    main_module.init_db()  # ensures tables exist on the fixture's temp engine
    session = main_module.SessionLocal()
    upsert_documents(
        session,
        [
            Document(
                drug="metformin",
                disease="stage iv pancreatic cancer",
                source="clinicaltrials",
                source_id=source_id,
                phase="phase 2",
                date=date(2026, 1, 1),
            )
        ],
    )
    upsert_approved_indications(
        session,
        [
            ApprovedIndication(
                drug="metformin",
                disease="type 2 diabetes mellitus",
                source="openfda",
                source_id="LABEL-TEST-0001",
            )
        ],
    )
    session.close()


def test_saving_a_case_snapshots_current_analysis(client):
    _seed_pancreatic_cancer_data()
    created = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{created['id']}/analyze")

    # Before saving: no snapshot yet, so recheck has nothing to compare against.
    response = client.post(f"/cases/{created['id']}/recheck")
    assert response.status_code == 400

    client.patch(f"/cases/{created['id']}", json={"saved": True})

    response = client.post(f"/cases/{created['id']}/recheck")
    assert response.status_code == 200
    body = response.json()
    assert body["has_new_evidence"] is False
    assert body["changes"] == []
    assert "No new evidence" in body["message"]


def test_recheck_requires_case_to_be_saved(client):
    _seed_pancreatic_cancer_data()
    created = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{created['id']}/analyze")

    response = client.post(f"/cases/{created['id']}/recheck")
    assert response.status_code == 400
    assert "saved" in response.json()["detail"].lower()


def test_recheck_unknown_case_returns_404(client):
    response = client.post("/cases/999999/recheck")
    assert response.status_code == 404


def test_recheck_detects_new_supporting_evidence_seeded_after_save(client):
    """Controlled/seeded verification (not live external data): seeds an
    initial trial, saves the case (snapshotting that state), then seeds a
    SECOND real-shaped trial document for the same drug/disease — standing
    in for "new data showed up on a later ingestion run" — and confirms the
    diff engine correctly detects the new supporting source."""
    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0001")
    created = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{created['id']}/analyze")
    client.patch(f"/cases/{created['id']}", json={"saved": True})

    # Simulate a later ingestion run finding a second trial for the same pair.
    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0002")

    response = client.post(f"/cases/{created['id']}/recheck")
    assert response.status_code == 200
    body = response.json()
    assert body["has_new_evidence"] is True
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["drug"] == "metformin"
    assert "NCT-TEST-0002" in change["new_supporting_source_ids"]
    assert change["is_new_candidate"] is False


def test_recheck_detects_newly_conflicted_comorbidity(client):
    """Controlled/seeded verification: saves a case with a comorbidity that
    initially has no matching contraindication text, then seeds a label
    update that introduces a real-shaped contraindication — standing in for
    an openFDA label being updated between ingestion runs — and confirms
    the diff engine surfaces it as a new context conflict."""
    from app.ingestion.store import upsert_approved_indications, upsert_documents
    from app.schemas.document import ApprovedIndication, Document
    from datetime import date

    main_module.init_db()
    session = main_module.SessionLocal()
    upsert_documents(
        session,
        [
            Document(
                drug="metformin",
                disease="stage iv pancreatic cancer",
                source="clinicaltrials",
                source_id="NCT-TEST-0001",
                phase="phase 2",
                date=date(2026, 1, 1),
            )
        ],
    )
    upsert_approved_indications(
        session,
        [
            ApprovedIndication(
                drug="metformin",
                disease="type 2 diabetes mellitus",
                source="openfda",
                source_id="LABEL-TEST-0001",
                contraindications=None,
            )
        ],
    )
    session.close()

    created = client.post(
        "/cases",
        json={
            "primary_condition": "pancreatic cancer",
            "comorbidities": ["renal impairment"],
            "current_medications": [],
        },
    ).json()
    client.post(f"/cases/{created['id']}/analyze")
    client.patch(f"/cases/{created['id']}", json={"saved": True})

    # A later ingestion run re-pulls the label and it now has contraindications text.
    session = main_module.SessionLocal()
    upsert_approved_indications(
        session,
        [
            ApprovedIndication(
                drug="metformin",
                disease="type 2 diabetes mellitus",
                source="openfda",
                source_id="LABEL-TEST-0002",
                contraindications="Contraindicated in patients with severe renal impairment.",
            )
        ],
    )
    session.close()

    response = client.post(f"/cases/{created['id']}/recheck")
    assert response.status_code == 200
    body = response.json()
    assert body["has_new_evidence"] is True
    change = body["changes"][0]
    assert change["newly_conflicted_comorbidities"] == ["renal impairment"]
    assert "clinical review required" in change["summary"]


def test_recheck_all_only_checks_saved_cases_and_summarizes(client):
    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0001")

    saved_case = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{saved_case['id']}/analyze")
    client.patch(f"/cases/{saved_case['id']}", json={"saved": True})

    unsaved_case = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{unsaved_case['id']}/analyze")
    # not saved -> should be skipped by recheck-all

    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0002")

    response = client.post("/cases/recheck-all")
    assert response.status_code == 200
    body = response.json()
    assert body["checked_count"] == 1
    assert body["cases_with_new_evidence_count"] == 1
    assert body["results"][0]["case_id"] == saved_case["id"]


def test_get_case_includes_last_evidence_check(client):
    _seed_pancreatic_cancer_data()
    created = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{created['id']}/analyze")
    client.patch(f"/cases/{created['id']}", json={"saved": True})

    before = client.get(f"/cases/{created['id']}").json()
    assert before["last_evidence_check"] is None

    client.post(f"/cases/{created['id']}/recheck")

    after = client.get(f"/cases/{created['id']}").json()
    assert after["last_evidence_check"] is not None
    assert after["last_evidence_check"]["has_new_evidence"] is False


# --- Duplicate-case prevention (TheraLens redesign Phase A, 2026-08-20) ----


def test_submitting_same_case_twice_reuses_existing_case(client):
    first = client.post(
        "/cases",
        json={
            "primary_condition": "pancreatic cancer",
            "comorbidities": ["renal impairment"],
            "current_medications": ["metformin"],
        },
    ).json()
    second = client.post(
        "/cases",
        json={
            "primary_condition": "Pancreatic Cancer",
            "comorbidities": ["Renal Impairment"],
            "current_medications": ["Metformin"],
        },
    ).json()

    assert second["id"] == first["id"]
    assert len(client.get("/cases").json()) == 1


def test_allow_duplicate_creates_a_second_case(client):
    first = client.post(
        "/cases",
        json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []},
    ).json()
    second = client.post(
        "/cases",
        json={
            "primary_condition": "pancreatic cancer",
            "comorbidities": [],
            "current_medications": [],
            "allow_duplicate": True,
        },
    ).json()

    assert second["id"] != first["id"]
    assert len(client.get("/cases").json()) == 2


def test_different_comorbidities_are_not_treated_as_duplicates(client):
    first = client.post(
        "/cases",
        json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []},
    ).json()
    second = client.post(
        "/cases",
        json={"primary_condition": "pancreatic cancer", "comorbidities": ["renal impairment"], "current_medications": []},
    ).json()

    assert second["id"] != first["id"]


# --- Cross-case conflicts endpoint ------------------------------------------


def test_conflicts_endpoint_empty_when_no_saved_cases_have_conflicts(client):
    response = client.get("/cases/conflicts")
    assert response.status_code == 200
    assert response.json() == []


def test_conflicts_endpoint_surfaces_source_backed_conflict(client):
    from app.ingestion.store import upsert_approved_indications, upsert_documents
    from app.schemas.document import ApprovedIndication, Document
    from datetime import date

    main_module.init_db()
    session = main_module.SessionLocal()
    upsert_documents(
        session,
        [
            Document(
                drug="metformin",
                disease="stage iv pancreatic cancer",
                source="clinicaltrials",
                source_id="NCT-CONFLICT-0001",
                phase="phase 2",
                date=date(2026, 1, 1),
            )
        ],
    )
    upsert_approved_indications(
        session,
        [
            ApprovedIndication(
                drug="metformin",
                disease="type 2 diabetes mellitus",
                source="openfda",
                source_id="LABEL-CONFLICT-0001",
                contraindications="Contraindicated in patients with severe renal impairment.",
            )
        ],
    )
    session.close()

    created = client.post(
        "/cases",
        json={
            "primary_condition": "pancreatic cancer",
            "comorbidities": ["renal impairment"],
            "current_medications": [],
        },
    ).json()
    client.post(f"/cases/{created['id']}/analyze")

    # Unsaved case: should not appear in the conflicts list yet.
    assert client.get("/cases/conflicts").json() == []

    client.patch(f"/cases/{created['id']}", json={"saved": True})

    response = client.get("/cases/conflicts")
    assert response.status_code == 200
    conflicts = response.json()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["case_id"] == created["id"]
    assert conflict["drug"] == "metformin"
    assert conflict["comorbidity"] == "renal impairment"
    assert "renal impairment" in conflict["evidence_excerpt"].lower()
    assert conflict["source"] == "openfda"


# --- Clean medication/condition autocomplete endpoints ----------------------


def test_medications_search_returns_clean_names(client, monkeypatch):
    from app.core.terminology import TerminologyResult

    monkeypatch.setattr(
        main_module, "search_medications", lambda q: ([TerminologyResult("Metformin")], False)
    )
    response = client.get("/medications/search", params={"q": "met"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"name": "Metformin"}]
    assert body["source_unavailable"] is False


def test_conditions_search_returns_clean_names(client, monkeypatch):
    from app.core.terminology import TerminologyResult

    monkeypatch.setattr(
        main_module, "search_conditions", lambda q: ([TerminologyResult("Heart Failure")], False)
    )
    response = client.get("/conditions/search", params={"q": "heart"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"name": "Heart Failure"}]


def test_list_cases_reflects_has_new_evidence_after_recheck(client):
    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0001")
    created = client.post(
        "/cases", json={"primary_condition": "pancreatic cancer", "comorbidities": [], "current_medications": []}
    ).json()
    client.post(f"/cases/{created['id']}/analyze")
    client.patch(f"/cases/{created['id']}", json={"saved": True})

    before = next(c for c in client.get("/cases").json() if c["id"] == created["id"])
    assert before["has_new_evidence"] is None

    _seed_pancreatic_cancer_data(source_id="NCT-TEST-0002")
    client.post(f"/cases/{created['id']}/recheck")

    after = next(c for c in client.get("/cases").json() if c["id"] == created["id"])
    assert after["has_new_evidence"] is True
    assert after["evidence_checked_at"] is not None
