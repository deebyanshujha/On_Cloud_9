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
