"""Clean, structured autocomplete for medications and conditions, backed by
the NLM Clinical Table Search Service (clinicaltables.nlm.nih.gov) —a free,
no-login REST API from the National Library of Medicine, purpose-built for
exactly this ("type a few letters, get back clean entity names"), consistent
with this project's "no paid/login APIs" constraint (same spirit as
RxNav/openFDA/ClinicalTrials.gov/Europe PMC already in use).

Why this instead of deriving suggestions from ingested data (the old
approach, `frontend/src/hooks/useEntityIndex.ts`): ingested data is either
too dirty (raw ClinicalTrials.gov intervention names include placebo/cohort
junk — see app.core.drug_normalization) or too verbose (openFDA
`indications_and_usage` is a full paragraph, not a disease name) to show
directly in a search-as-you-type dropdown. This module never touches
ingested data — it's a separate, authoritative name source. Two endpoints:

- RxTerms (`/api/rxterms/v3/search`) for medications — curated for
  prescribing/autocomplete use cases, so it already excludes placebo-style
  noise by construction.
- `conditions` (`/api/conditions/v3/search`) for diseases — ICD-10-CM-backed
  clean condition names.

Both follow the same never-raises-on-network-failure spirit as
`app.core.drug_normalization.resolve_rxnorm_id`: a source outage returns an
empty result list with `source_unavailable=True`, never a 500.
"""
from __future__ import annotations

import httpx

RXTERMS_SEARCH_URL = "https://clinicaltables.nlm.nih.gov/api/rxterms/v3/search"
CONDITIONS_SEARCH_URL = "https://clinicaltables.nlm.nih.gov/api/conditions/v3/search"

_TIMEOUT = 5.0
_MAX_RESULTS = 20


class TerminologyResult:
    """Plain container (not a pydantic model — this is core logic, the API
    layer wraps it in a response schema) for one autocomplete hit."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, TerminologyResult) and self.name == other.name

    def __repr__(self):
        return f"TerminologyResult({self.name!r})"


def search_medications(query: str) -> tuple[list[TerminologyResult], bool]:
    """Returns (results, source_unavailable). RxTerms' raw response shape is
    a 4-element array: [total_count, codes, extra_fields_dict, display_strings].
    display_strings is a list of [name] pairs (index-aligned with codes) —
    we only need the clean name."""
    query = query.strip()
    if not query:
        return [], False

    try:
        response = httpx.get(
            RXTERMS_SEARCH_URL,
            params={"terms": query, "maxList": _MAX_RESULTS},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        display_strings = payload[3] if len(payload) > 3 else []
        names = [row[0] for row in display_strings if row and row[0]]
    except (httpx.HTTPError, ValueError, IndexError, TypeError, KeyError):
        return [], True

    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return [TerminologyResult(name) for name in list(seen)[:_MAX_RESULTS]], False


def search_conditions(query: str) -> tuple[list[TerminologyResult], bool]:
    """Same response shape as RxTerms (the whole Clinical Table Search
    Service family uses this [total, codes, extra_fields, display_strings]
    convention) — the `conditions` table's display string is the clean
    condition name."""
    query = query.strip()
    if not query:
        return [], False

    try:
        response = httpx.get(
            CONDITIONS_SEARCH_URL,
            params={"terms": query, "maxList": _MAX_RESULTS},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        display_strings = payload[3] if len(payload) > 3 else []
        names = [row[0] for row in display_strings if row and row[0]]
    except (httpx.HTTPError, ValueError, IndexError, TypeError, KeyError):
        return [], True

    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return [TerminologyResult(name) for name in list(seen)[:_MAX_RESULTS]], False
