"""Tests app/core/search.py's relevance ranking in isolation (no API/DB
dependency) — 2026-08-20 fix for /search returning an unranked, unbounded
substring match over everything (see PROGRESS.md)."""
from datetime import date

from app.core.search import rank_search_results
from app.schemas.api import SignalOut


def make_signal(drug, disease, score=0.5, first_detected=None) -> SignalOut:
    return SignalOut(
        drug=drug,
        disease=disease,
        score=score,
        reasons=[],
        approved_for=[],
        num_independent_sources=1,
        source_breakdown={},
        first_detected=first_detected,
        sources=[],
    )


def test_exact_match_ranks_above_prefix_and_substring():
    signals = [
        make_signal("metformin-plus", "x"),  # substring/prefix on drug
        make_signal("metformin", "x"),  # exact
        make_signal("some drug", "metformin analog"),  # substring on disease
    ]
    ranked = rank_search_results(signals, "metformin")
    assert ranked[0].drug == "metformin"


def test_prefix_match_ranks_above_substring_match():
    signals = [
        make_signal("xmetformin", "x"),  # substring only
        make_signal("metforminx", "x"),  # prefix
    ]
    ranked = rank_search_results(signals, "metformin")
    assert ranked[0].drug == "metforminx"


def test_ties_broken_by_score_then_recency():
    signals = [
        make_signal("aspirin", "d1", score=0.3, first_detected=date(2020, 1, 1)),
        make_signal("aspirin", "d2", score=0.9, first_detected=date(2019, 1, 1)),
        make_signal("aspirin", "d3", score=0.9, first_detected=date(2024, 1, 1)),
    ]
    ranked = rank_search_results(signals, "aspirin")
    assert [s.disease for s in ranked] == ["d3", "d2", "d1"]


def test_non_matching_signals_are_excluded():
    signals = [make_signal("aspirin", "headache"), make_signal("metformin", "diabetes")]
    ranked = rank_search_results(signals, "zzz-nomatch")
    assert ranked == []


def test_matches_against_disease_field_too():
    signals = [make_signal("drugA", "pancreatic cancer")]
    ranked = rank_search_results(signals, "pancreatic")
    assert len(ranked) == 1
