"""Tests for app/core/terminology.py — clean medication/condition
autocomplete backed by NLM's Clinical Table Search Service. Mocks httpx.get
so the suite never touches the real network."""
import httpx

import app.core.terminology as terminology


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


RXTERMS_PAYLOAD = [
    3,
    ["code1", "code2", "code3"],
    {},
    [["Metformin"], ["Metoprolol"], ["Methotrexate"]],
]

CONDITIONS_PAYLOAD = [
    2,
    ["icd1", "icd2"],
    {},
    [["Heart Failure"], ["Heart Failure with Reduced Ejection Fraction"]],
]


def test_search_medications_returns_clean_names(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(RXTERMS_PAYLOAD))
    results, unavailable = terminology.search_medications("met")
    assert unavailable is False
    names = [r.name for r in results]
    assert names == ["Metformin", "Metoprolol", "Methotrexate"]


def test_search_medications_never_returns_label_paragraphs(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(RXTERMS_PAYLOAD))
    results, _ = terminology.search_medications("met")
    for r in results:
        assert len(r.name) < 40
        assert "INDICATIONS AND USAGE" not in r.name


def test_search_conditions_returns_clean_names(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(CONDITIONS_PAYLOAD))
    results, unavailable = terminology.search_conditions("heart")
    assert unavailable is False
    assert [r.name for r in results] == [
        "Heart Failure",
        "Heart Failure with Reduced Ejection Fraction",
    ]


def test_empty_query_returns_no_results_without_network_call(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: called.append(1) or FakeResponse(RXTERMS_PAYLOAD))
    results, unavailable = terminology.search_medications("")
    assert results == []
    assert unavailable is False
    assert called == []


def test_network_failure_returns_empty_and_flags_unavailable(monkeypatch):
    def raise_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", raise_error)
    results, unavailable = terminology.search_medications("met")
    assert results == []
    assert unavailable is True


def test_http_error_status_returns_empty_and_flags_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse({}, status_code=500))
    results, unavailable = terminology.search_conditions("heart")
    assert results == []
    assert unavailable is True


def test_unexpected_shape_returns_empty_without_raising(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse({"unexpected": "shape"}))
    results, unavailable = terminology.search_medications("met")
    assert results == []


def test_malformed_payload_never_raises(monkeypatch):
    # display_strings (index 3) is None instead of a list -> would raise
    # TypeError iterating it if not for the never-raises try/except.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse([1, 2, 3, None]))
    results, unavailable = terminology.search_medications("met")
    assert results == []
    assert unavailable is True
