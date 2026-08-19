"""Tests for the FastAPI read layer (Step 8). Builds signals directly from
the Step 2 fixture (backend/data/known_cases.json) rather than hitting the
real arbitrage.db, so the suite doesn't depend on ingestion scripts having
been run first."""
from fastapi.testclient import TestClient

from app.core.fixtures import load_known_cases
from app.core.scoring import run_comparison
from app.main import app
from app.schemas.api import build_signal_out


def make_client() -> TestClient:
    documents, approved = load_known_cases()
    signals = run_comparison(documents, approved)
    app.state.signals = [build_signal_out(s) for s in signals]
    return TestClient(app)


def test_health():
    client = make_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_signals_returns_all_known_cases():
    client = make_client()
    response = client.get("/signals")
    assert response.status_code == 200
    pairs = {(s["drug"], s["disease"]) for s in response.json()}
    assert ("metformin", "pancreatic cancer") in pairs
    assert ("sildenafil", "pulmonary hypertension") in pairs
    assert ("thalidomide", "multiple myeloma") in pairs


def test_list_signals_are_sorted_by_score_desc():
    client = make_client()
    response = client.get("/signals")
    scores = [s["score"] for s in response.json()]
    assert scores == sorted(scores, reverse=True)


def test_signal_has_expected_shape():
    client = make_client()
    response = client.get("/signals")
    signal = next(
        s
        for s in response.json()
        if (s["drug"], s["disease"]) == ("metformin", "pancreatic cancer")
    )
    assert signal["num_independent_sources"] == 2
    assert signal["source_breakdown"] == {"clinicaltrials": 1, "biorxiv": 1}
    assert signal["approved_for"] == ["type 2 diabetes"]
    assert signal["first_detected"] == "2025-09-02"
    assert len(signal["sources"]) == 2
    assert all(src["url"] for src in signal["sources"])


def test_signals_for_drug():
    client = make_client()
    response = client.get("/signals/metformin")
    assert response.status_code == 200
    assert all(s["drug"] == "metformin" for s in response.json())


def test_signals_for_drug_is_case_insensitive():
    client = make_client()
    response = client.get("/signals/METFORMIN")
    assert response.status_code == 200
    assert len(response.json()) > 0


def test_signals_for_unknown_drug_returns_404():
    client = make_client()
    response = client.get("/signals/not-a-real-drug")
    assert response.status_code == 404


def test_search_matches_drug():
    client = make_client()
    response = client.get("/search", params={"q": "metformin"})
    assert response.status_code == 200
    assert all(s["drug"] == "metformin" for s in response.json())


def test_search_matches_disease():
    client = make_client()
    response = client.get("/search", params={"q": "myeloma"})
    assert response.status_code == 200
    diseases = {s["disease"] for s in response.json()}
    assert "multiple myeloma" in diseases


def test_search_empty_query_returns_empty_list():
    client = make_client()
    response = client.get("/search", params={"q": "   "})
    assert response.status_code == 200
    assert response.json() == []


def test_search_no_matches_returns_empty_list():
    client = make_client()
    response = client.get("/search", params={"q": "zzz-nonexistent"})
    assert response.status_code == 200
    assert response.json() == []
