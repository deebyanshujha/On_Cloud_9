"""Tests for the Phase 4 LLM interpretation layer
(app/core/llm_interpreter.py), which calls Google's Gemini API. No live
Gemini API call is ever made here — `_call_llm` is the sole network seam
and is monkeypatched directly, the same pattern test_runtime_research.py
uses for `_fetch_papers_for_query_safe`/`resolve_rxnorm_id`.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core import llm_interpreter
from app.schemas.case import CandidateOut, ComorbidityCheck, CurrentMedicationInteractionNote


def _candidate(**overrides) -> CandidateOut:
    defaults = dict(
        drug="metformin",
        disease="pancreatic cancer",
        research_priority_score=0.72,
        evidence_strength_score=0.8,
        known_indications=["type 2 diabetes mellitus"],
        evidence_tier="moderate",
        evidence_tier_reason="2 clinical trials",
        primary_condition_evidence=[],
        comorbidity_checks=[],
        current_medication_interactions=CurrentMedicationInteractionNote(),
        reasoning_trail=["known indication -> new disease association"],
    )
    defaults.update(overrides)
    return CandidateOut(**defaults)


def _gemini_response(summary: str, caveats: list[str]) -> dict:
    """Shape of a real Gemini generateContent response, trimmed to the
    fields this module actually reads."""
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": json.dumps({"summary": summary, "caveats": caveats})}],
                },
                "finishReason": "STOP",
            }
        ]
    }


# --- is_configured -----------------------------------------------------


def test_is_configured_false_without_api_key(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", None)
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    assert llm_interpreter.is_configured() is False


def test_is_configured_false_when_disabled_by_config(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", False)
    assert llm_interpreter.is_configured() is False


def test_is_configured_true_with_key_and_enabled(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    assert llm_interpreter.is_configured() is True


# --- _build_prompt: grounding -------------------------------------------


def test_build_prompt_only_contains_candidate_fields():
    candidate = _candidate(
        comorbidity_checks=[
            ComorbidityCheck(comorbidity="renal impairment", status="conflict_detected", evidence="excerpt")
        ]
    )
    prompt = llm_interpreter._build_prompt(candidate, primary_condition="pancreatic cancer")
    payload = json.loads(prompt)

    assert payload["drug"] == "metformin"
    assert payload["disease"] == "pancreatic cancer"
    assert payload["case_primary_condition"] == "pancreatic cancer"
    assert payload["known_indications"] == ["type 2 diabetes mellitus"]
    assert payload["comorbidity_checks"] == [
        {"comorbidity": "renal impairment", "status": "conflict_detected", "evidence": "excerpt"}
    ]
    # No fabricated fields beyond what the candidate itself carries.
    assert set(payload.keys()) == {
        "case_primary_condition",
        "drug",
        "disease",
        "research_priority_score",
        "evidence_strength_score",
        "evidence_tier",
        "evidence_tier_reason",
        "known_indications",
        "reasoning_trail",
        "comorbidity_checks",
        "supporting_evidence_count",
    }


# --- interpret_candidate: degrade-cleanly behavior ----------------------


def test_interpret_candidate_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", None)
    candidate = _candidate()
    assert llm_interpreter.interpret_candidate(candidate, primary_condition="x") is None


def test_interpret_candidate_success(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    monkeypatch.setattr(llm_interpreter, "LLM_MODEL", "gemini-2.5-flash")

    def fake_call_llm(prompt: str) -> str:
        return json.dumps(
            {"summary": "Metformin shows early signal for pancreatic cancer.", "caveats": ["sparse evidence"]}
        )

    monkeypatch.setattr(llm_interpreter, "_call_llm", fake_call_llm)

    result = llm_interpreter.interpret_candidate(_candidate(), primary_condition="pancreatic cancer")
    assert result is not None
    assert result.summary == "Metformin shows early signal for pancreatic cancer."
    assert result.caveats == ["sparse evidence"]
    assert result.model == "gemini-2.5-flash"


def test_interpret_candidate_handles_malformed_json(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    monkeypatch.setattr(llm_interpreter, "_call_llm", lambda prompt: "not json at all")

    assert llm_interpreter.interpret_candidate(_candidate(), primary_condition="x") is None


def test_interpret_candidate_handles_missing_summary_key(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    monkeypatch.setattr(llm_interpreter, "_call_llm", lambda prompt: json.dumps({"caveats": []}))

    assert llm_interpreter.interpret_candidate(_candidate(), primary_condition="x") is None


def test_interpret_candidate_handles_http_error(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)

    def raising_call(prompt: str) -> str:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(llm_interpreter, "_call_llm", raising_call)

    assert llm_interpreter.interpret_candidate(_candidate(), primary_condition="x") is None


def test_call_llm_parses_real_gemini_response_shape(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_MODEL", "gemini-2.5-flash")

    def fake_post(url, *, headers, json, timeout):
        assert "gemini-2.5-flash" in url
        assert headers["x-goog-api-key"] == "test-key"
        # Key must never appear in the URL (would land in access logs).
        assert "test-key" not in url
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200,
            json=_gemini_response("ok summary", ["a caveat"]),
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    raw_text = llm_interpreter._call_llm("some prompt")
    parsed = json.loads(raw_text)
    assert parsed == {"summary": "ok summary", "caveats": ["a caveat"]}


def test_call_llm_raises_on_non_2xx(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")

    def fake_post(*args, **kwargs):
        request = httpx.Request(
            "POST", llm_interpreter.GEMINI_GENERATE_URL_TEMPLATE.format(model=llm_interpreter.LLM_MODEL)
        )
        return httpx.Response(status_code=401, json={"error": "unauthorized"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(httpx.HTTPError):
        llm_interpreter._call_llm("some prompt")


def test_call_llm_raises_on_empty_candidates(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")

    def fake_post(*args, **kwargs):
        request = httpx.Request(
            "POST", llm_interpreter.GEMINI_GENERATE_URL_TEMPLATE.format(model=llm_interpreter.LLM_MODEL)
        )
        return httpx.Response(status_code=200, json={"candidates": []}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(ValueError):
        llm_interpreter._call_llm("some prompt")


# --- interpret_candidates: batch behavior -------------------------------


def test_interpret_candidates_no_candidates_short_circuits(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    candidates, status = llm_interpreter.interpret_candidates([], primary_condition="x")
    assert candidates == []
    assert status == "no_candidates"


def test_interpret_candidates_disabled_no_api_key_leaves_candidates_untouched(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", None)
    candidate = _candidate()
    candidates, status = llm_interpreter.interpret_candidates([candidate], primary_condition="x")
    assert status == "disabled_no_api_key"
    assert candidates[0].llm_interpretation is None


def test_interpret_candidates_disabled_by_config(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", False)
    candidate = _candidate()
    candidates, status = llm_interpreter.interpret_candidates([candidate], primary_condition="x")
    assert status == "disabled_by_config"
    assert candidates[0].llm_interpretation is None


def test_interpret_candidates_attaches_only_to_top_n(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    monkeypatch.setattr(llm_interpreter, "LLM_MAX_CANDIDATES", 1)
    monkeypatch.setattr(
        llm_interpreter,
        "_call_llm",
        lambda prompt: json.dumps({"summary": "ok", "caveats": []}),
    )

    first = _candidate(drug="metformin")
    second = _candidate(drug="sildenafil")
    candidates, status = llm_interpreter.interpret_candidates([first, second], primary_condition="x")

    assert candidates[0].llm_interpretation is not None
    assert candidates[1].llm_interpretation is None
    assert status == "success (1 candidate(s) interpreted)"


def test_interpret_candidates_all_fail_reports_attempted_but_failed(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_interpreter, "LLM_INTERPRETATION_ENABLED", True)
    monkeypatch.setattr(llm_interpreter, "_call_llm", lambda prompt: "not json")

    candidates, status = llm_interpreter.interpret_candidates([_candidate()], primary_condition="x")
    assert status == "attempted_but_failed"
    assert candidates[0].llm_interpretation is None
