"""Runtime configuration for the discovery pipeline (Step 10).

Everything here is read from environment variables at import time, with
sane defaults, so changing a limit (e.g. scan size 10 -> 50) is a config
change, not a code change. No file needs editing to take effect — just set
the env var before running a script (`ARB_MAX_RESULTS_PER_SOURCE=50 py
scripts/run_pipeline.py`).
"""
from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


# Max results (studies / preprints) to scan per discovery source, per run.
# The acceptance test for this knob: setting it to 50 instead of 10 makes
# the pipeline attempt up to 50 results per source, with zero code edits.
MAX_RESULTS_PER_SOURCE = _int_env("ARB_MAX_RESULTS_PER_SOURCE", 10)

# How far back (in days) discovery queries look for new trials/preprints.
TIME_WINDOW_DAYS = _int_env("ARB_TIME_WINDOW_DAYS", 90)

# Signals scoring below this are not surfaced by the comparison engine.
MIN_CONFIDENCE_SCORE = _float_env("ARB_MIN_CONFIDENCE_SCORE", 0.0)

# openFDA labels fetched per discovered drug (reactive lookup, not a scan).
OPENFDA_LABELS_PER_DRUG = _int_env("ARB_OPENFDA_LABELS_PER_DRUG", 10)

# Page size per request for paginated sources.
PAGE_SIZE = _int_env("ARB_PAGE_SIZE", 50)

# Fair-budget cap (2026-08-20 data-imbalance fix): the most documents any
# single drug is allowed to contribute to scoring, regardless of how many it
# actually has in the DB. Guards against one drug's real-world trial volume
# structurally dwarfing every other drug's signals the way the old
# pre-discovery metformin/sildenafil bulk ingestion did (see
# scripts/clear_legacy_bulk_data.py and PROGRESS.md for the audit that found
# it) — this is the forward-looking half of that fix, the cleanup script is
# the backward-looking half. Default chosen from the real post-cleanup
# distribution: the most-documented dynamically-discovered drug currently
# has 18 documents, so 50 gives real headroom (~3x) before the cap ever
# engages under normal operation, while still bounding runaway skew.
MAX_DOCUMENTS_PER_DRUG = _int_env("ARB_MAX_DOCUMENTS_PER_DRUG", 50)

# Default number of results /search returns per page.
SEARCH_RESULT_LIMIT = _int_env("ARB_SEARCH_RESULT_LIMIT", 20)

# Max research candidates a single case analysis returns (highest
# research_priority_score first). Unbounded candidate lists were the
# "203 signals dumped on screen" problem one level up (see PROGRESS.md) —
# this is the case-analysis-specific version of the same fix: a case page
# should answer "what's worth investigating," not enumerate every matching
# signal.
MAX_CANDIDATES_PER_CASE = _int_env("ARB_MAX_CANDIDATES_PER_CASE", 10)

# Runtime case research budgets. These are separate from global discovery:
# a case run is user-triggered and should gather enough source-backed
# evidence to answer that case, without dumping unrelated global signals.
CASE_RESEARCH_TIME_WINDOW_DAYS = _int_env("ARB_CASE_RESEARCH_TIME_WINDOW_DAYS", 3650)
CASE_RESEARCH_MAX_PAPERS = _int_env("ARB_CASE_RESEARCH_MAX_PAPERS", 50)
CASE_RESEARCH_MAX_TRIALS = _int_env("ARB_CASE_RESEARCH_MAX_TRIALS", 50)
CASE_RESEARCH_RESULTS_PER_QUERY = _int_env("ARB_CASE_RESEARCH_RESULTS_PER_QUERY", 10)

# Retry/backoff for case-research HTTP calls (Europe PMC, PubMed,
# ClinicalTrials.gov). Retries only apply to outcomes that might genuinely
# succeed on a second attempt (timeouts, 429 rate-limiting, 5xx) — never to
# a clean HTTP 200 with zero hits, and never to a 4xx client error or
# malformed-JSON response, since retrying those wastes a request budget on
# something a retry can't fix. See app/core/runtime_research.py's
# `_request_with_retry`.
CASE_RESEARCH_MAX_RETRIES = _int_env("ARB_CASE_RESEARCH_MAX_RETRIES", 2)
CASE_RESEARCH_RETRY_BACKOFF_SECONDS = _float_env("ARB_CASE_RESEARCH_RETRY_BACKOFF_SECONDS", 0.5)

# PubMed E-utilities (NCBI) is rate-limited to 3 req/sec without an API key
# (10/sec with one — ARB_NCBI_API_KEY, optional). This caps how many PubMed
# requests this process issues concurrently, independent of the general
# CASE_RESEARCH_FETCH_WORKERS thread-pool size used for Europe PMC/CT.gov,
# so a case with many queries can't trip NCBI's rate limit.
PUBMED_MAX_CONCURRENT_REQUESTS = _int_env("ARB_PUBMED_MAX_CONCURRENT_REQUESTS", 3)
NCBI_API_KEY = os.environ.get("ARB_NCBI_API_KEY") or None
