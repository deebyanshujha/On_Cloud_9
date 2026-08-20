"""Shared HTTP GET + retry/backoff + outcome-classification helper for the
case-research retrieval layer (Europe PMC, PubMed, ClinicalTrials.gov).

Centralized here so all three sources classify a failure the same way —
timeout vs rate-limited vs http_error vs parse_error vs a clean empty
result — instead of each adapter inventing its own ad hoc try/except and
collapsing every failure mode into "evidence_gaps got a string appended."
That collapsing is exactly what let a genuine Europe PMC/ClinicalTrials.gov
outage look identical to "this case has no evidence" in research_metadata
before this module existed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx

FetchStatus = Literal[
    "success", "timeout", "http_error", "parse_error", "rate_limited"
]


@dataclass
class FetchOutcome:
    """Result of one retried GET. `response` is only set on `"success"` —
    callers decode the body themselves (JSON for Europe PMC/CT.gov, XML for
    PubMed EFetch) and should turn a decode failure into their own
    `parse_error` outcome rather than assuming JSON here."""

    status: FetchStatus
    response: httpx.Response | None = None
    error: str | None = None
    attempts: int = 1


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict,
    *,
    max_retries: int = 2,
    backoff_seconds: float = 0.5,
) -> FetchOutcome:
    """GET `url` and classify the outcome, retrying only failure modes a
    second attempt can plausibly fix:

    - timeouts and 5xx server errors: exponential backoff, retried
    - 429: retried, honoring `Retry-After` if the server sends one
    - 4xx (other than 429): returned immediately, never retried — the
      same request will fail again
    - a successful 2xx response is returned immediately as `"success"`
      with the raw `httpx.Response` for the caller to decode

    Never raises — every httpx exception and non-2xx status is captured
    and classified into `FetchOutcome.status` instead.
    """
    last_error: str | None = None
    attempt = 0
    while attempt <= max_retries:
        try:
            response = client.get(url, params=params)
        except httpx.TimeoutException as exc:
            last_error = f"timeout: {exc}"
            if attempt < max_retries:
                time.sleep(backoff_seconds * (2**attempt))
                attempt += 1
                continue
            return FetchOutcome(status="timeout", error=last_error, attempts=attempt + 1)
        except httpx.HTTPError as exc:
            last_error = f"request failed: {exc}"
            if attempt < max_retries:
                time.sleep(backoff_seconds * (2**attempt))
                attempt += 1
                continue
            return FetchOutcome(status="http_error", error=last_error, attempts=attempt + 1)

        if response.status_code == 429:
            last_error = f"rate limited (429): {response.text[:200]}"
            if attempt < max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.strip().isdigit()
                    else backoff_seconds * (2**attempt)
                )
                time.sleep(delay)
                attempt += 1
                continue
            return FetchOutcome(status="rate_limited", error=last_error, attempts=attempt + 1)

        if response.status_code >= 500:
            last_error = f"server error ({response.status_code}): {response.text[:200]}"
            if attempt < max_retries:
                time.sleep(backoff_seconds * (2**attempt))
                attempt += 1
                continue
            return FetchOutcome(status="http_error", error=last_error, attempts=attempt + 1)

        if response.status_code >= 400:
            # Client error (400/404/...) — the same request will fail the
            # same way again, so retrying just burns the request budget.
            return FetchOutcome(
                status="http_error",
                error=f"client error ({response.status_code}): {response.text[:200]}",
                attempts=attempt + 1,
            )

        return FetchOutcome(status="success", response=response, attempts=attempt + 1)

    return FetchOutcome(status="http_error", error=last_error or "unknown failure", attempts=attempt + 1)
