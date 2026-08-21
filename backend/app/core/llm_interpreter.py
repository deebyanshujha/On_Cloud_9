"""Phase 4: LLM interpretation layer.

This module adds a purely additive, optional interpretive layer on top of
the deterministic candidate list produced by app/core/case_analysis.py. It
does NOT replace or second-guess any part of the deterministic pipeline
(retrieval, disease matching, scoring, comorbidity checks) — it only reads
the already-computed, already-validated CandidateOut fields (reasoning_trail,
comorbidity_checks, known_indications, evidence_tier) and asks the model to
restate them in plain language for a clinician audience, plus flag any
caveats a careful reader should hold onto. The model is explicitly
instructed never to introduce a new drug, disease, or claim that isn't
already present in the structured evidence passed to it.

Provider note: originally built against Anthropic's Claude Messages API
(per the Phase 4 brief); switched to Google's Gemini API on 2026-08-20 at
the user's explicit request, because only a Gemini key was available for
live verification in this environment — see PROGRESS.md's Phase 4 entry
for the full record. Naming throughout this module/schema/config is
provider-neutral (LLM_*, not CLAUDE_*/GEMINI_*) so a future provider swap
is a `_call_llm` rewrite, not another rename.

Isolated and mockable: `_call_llm` is the only network seam, patched in
tests the same way `resolve_rxnorm_id`/`_fetch_papers_for_query_safe` are
patched in test_runtime_research.py — no live Gemini API call is ever made
in the automated test suite.

Cleanly degrades: no API key, a disabled flag, a timeout, an HTTP error, or
a malformed response all result in `CandidateOut.llm_interpretation` staying
None for the affected candidate(s) — this layer can never fail case
analysis itself.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.core.config import (
    GEMINI_API_KEY,
    LLM_INTERPRETATION_ENABLED,
    LLM_MAX_CANDIDATES,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_REQUEST_TIMEOUT_SECONDS,
)
from app.schemas.case import CandidateOut, LLMInterpretation

GEMINI_GENERATE_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_SYSTEM_PROMPT = (
    "You are assisting a clinical researcher reading an automatically "
    "generated drug-repurposing research candidate. You will be given "
    "already-computed, already-validated structured evidence for exactly "
    "one drug-disease candidate. Restate it in clear, plain language for a "
    "clinician audience, and note any caveats a careful reader should hold "
    "onto (e.g. sparse evidence, an unresolved comorbidity conflict, a low "
    "evidence tier). Do not introduce any drug, disease, mechanism, or "
    "claim that is not already present in the evidence given to you. This "
    "is a research signal, never a treatment recommendation. Respond with "
    "ONLY a JSON object of the shape "
    '{"summary": "...", "caveats": ["...", ...]}, no other text.'
)


def is_configured() -> bool:
    """True only when both an API key is set and the layer hasn't been
    explicitly disabled via config."""
    return bool(GEMINI_API_KEY) and LLM_INTERPRETATION_ENABLED


def _build_prompt(candidate: CandidateOut, *, primary_condition: str) -> str:
    """Serializes only fields already present on `candidate` — this is the
    entire evidence surface the model ever sees for this call."""
    payload = {
        "case_primary_condition": primary_condition,
        "drug": candidate.drug,
        "disease": candidate.disease,
        "research_priority_score": candidate.research_priority_score,
        "evidence_strength_score": candidate.evidence_strength_score,
        "evidence_tier": candidate.evidence_tier,
        "evidence_tier_reason": candidate.evidence_tier_reason,
        "known_indications": candidate.known_indications,
        "reasoning_trail": candidate.reasoning_trail,
        "comorbidity_checks": [
            {
                "comorbidity": check.comorbidity,
                "status": check.status,
                "evidence": check.evidence,
            }
            for check in candidate.comorbidity_checks
        ],
        "supporting_evidence_count": len(candidate.primary_condition_evidence),
    }
    return json.dumps(payload, default=str)


def _call_llm(prompt: str) -> str:
    """The only network seam in this module — patched directly in tests.

    Calls Google's Gemini `generateContent` API. Returns the raw text of
    the model's reply. Raises (httpx.HTTPError, ValueError) on any
    failure; callers decide how to degrade. The API key is sent only in a
    request header (`x-goog-api-key`), never in the URL, so it can't end
    up in access logs that record request paths/query strings."""
    url = GEMINI_GENERATE_URL_TEMPLATE.format(model=LLM_MODEL)
    response = httpx.post(
        url,
        headers={
            "x-goog-api-key": GEMINI_API_KEY or "",
            "content-type": "application/json",
        },
        json={
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": LLM_MAX_TOKENS,
                "responseMimeType": "application/json",
            },
        },
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response had no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise ValueError("Gemini response had no text content")
    return text


def _parse_interpretation(raw_text: str) -> LLMInterpretation:
    parsed = json.loads(raw_text)
    summary = parsed.get("summary")
    if not summary or not isinstance(summary, str):
        raise ValueError("LLM response JSON missing a 'summary' string")
    caveats = parsed.get("caveats")
    if not isinstance(caveats, list):
        caveats = []
    return LLMInterpretation(
        summary=summary,
        caveats=[str(c) for c in caveats],
        model=LLM_MODEL,
        generated_at=datetime.now(timezone.utc),
    )


def interpret_candidate(
    candidate: CandidateOut, *, primary_condition: str
) -> LLMInterpretation | None:
    """Returns None (never raises) if the LLM layer is not configured, or
    if the call/parse fails for any reason — the deterministic candidate
    is always complete and usable with or without this layer."""
    if not is_configured():
        return None
    try:
        prompt = _build_prompt(candidate, primary_condition=primary_condition)
        raw_text = _call_llm(prompt)
        return _parse_interpretation(raw_text)
    except (httpx.HTTPError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        return None


def interpret_candidates(
    candidates: list[CandidateOut], *, primary_condition: str
) -> tuple[list[CandidateOut], str]:
    """Attaches an LLM interpretation to the top `LLM_MAX_CANDIDATES`
    candidates in place (candidates are already sorted by
    research_priority_score by app.core.case_analysis.analyze_case). Never
    reorders, drops, or otherwise modifies any candidate field.

    Returns `(candidates, status)` where `status` is a short human-readable
    string describing what happened this run, meant for
    ResearchMetadata.llm_interpretation_status.
    """
    if not candidates:
        return candidates, "no_candidates"
    if not GEMINI_API_KEY:
        return candidates, "disabled_no_api_key"
    if not LLM_INTERPRETATION_ENABLED:
        return candidates, "disabled_by_config"

    interpreted_count = 0
    for candidate in candidates[:LLM_MAX_CANDIDATES]:
        interpretation = interpret_candidate(candidate, primary_condition=primary_condition)
        if interpretation is not None:
            candidate.llm_interpretation = interpretation
            interpreted_count += 1

    if interpreted_count == 0:
        return candidates, "attempted_but_failed"
    return candidates, f"success ({interpreted_count} candidate(s) interpreted)"
