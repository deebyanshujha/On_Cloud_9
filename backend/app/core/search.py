"""Relevance ranking for /search (2026-08-20 fix for "too much comes back
per query" — see PROGRESS.md). Previously /search just filtered
`app.state.signals` by substring match and returned everything, in
whatever order signals happened to already be in (score-sorted from
run_comparison, not relevance to the query). This ranks by how well a
signal actually matches the query first, then falls back to the existing
score/recency signals as tiebreaks.

Pure function over SignalOut, no FastAPI/DB dependency, so it's testable in
isolation from the endpoint.
"""
from __future__ import annotations

from datetime import date as date_

from app.schemas.api import SignalOut

# Lower tier = better match.
_EXACT = 0
_STARTS_WITH = 1
_SUBSTRING = 2
_NO_MATCH = 3


def _match_tier(field: str, query: str) -> int:
    if field == query:
        return _EXACT
    if field.startswith(query):
        return _STARTS_WITH
    if query in field:
        return _SUBSTRING
    return _NO_MATCH


def _best_tier(signal: SignalOut, query: str) -> int:
    return min(_match_tier(signal.drug, query), _match_tier(signal.disease, query))


def rank_search_results(signals: list[SignalOut], query: str) -> list[SignalOut]:
    """Returns only signals that match `query` (already-normalized: stripped
    + lowercased) against drug or disease, ranked best-match-first. Ties
    broken by the signal's existing score (higher first), then recency
    (more recently first-detected first)."""
    matches = [(s, _best_tier(s, query)) for s in signals]
    matches = [(s, tier) for s, tier in matches if tier != _NO_MATCH]
    matches.sort(
        key=lambda pair: (
            pair[1],
            -pair[0].score,
            -(pair[0].first_detected or date_.min).toordinal(),
        )
    )
    return [s for s, _tier in matches]
