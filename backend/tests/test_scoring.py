"""Proves the core comparison/scoring engine (app/core/scoring.py) against
the three known repurposing examples before any real data source is wired
up: metformin -> pancreatic cancer, sildenafil -> pulmonary hypertension,
thalidomide -> multiple myeloma. Also proves it correctly does NOT flag a
drug for a disease it's already approved for.
"""
from datetime import date

from app.core.fixtures import load_known_cases
from app.core.scoring import run_comparison


def test_rediscovers_known_repurposing_signals():
    documents, approved = load_known_cases()

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    signal_pairs = {(s.drug, s.disease) for s in signals}
    assert ("metformin", "pancreatic cancer") in signal_pairs
    assert ("sildenafil", "pulmonary hypertension") in signal_pairs
    assert ("thalidomide", "multiple myeloma") in signal_pairs


def test_does_not_flag_already_approved_pair():
    documents, approved = load_known_cases()

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    signal_pairs = {(s.drug, s.disease) for s in signals}
    assert ("metformin", "type 2 diabetes") not in signal_pairs


def test_signals_are_sorted_highest_score_first():
    documents, approved = load_known_cases()

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    scores = [s.score for s in signals]
    assert scores == sorted(scores, reverse=True)


def test_metformin_pancreatic_cancer_has_two_independent_mentions():
    documents, approved = load_known_cases()

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    metformin_signal = next(
        s for s in signals if (s.drug, s.disease) == ("metformin", "pancreatic cancer")
    )
    assert len(metformin_signal.supporting_documents) == 2
    assert metformin_signal.approved_for == ["type 2 diabetes"]


def test_score_is_between_zero_and_one():
    documents, approved = load_known_cases()

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    for s in signals:
        assert 0.0 <= s.score <= 1.0


def test_min_score_filters_low_confidence_signals():
    documents, approved = load_known_cases()

    all_signals = run_comparison(documents, approved, today=date(2026, 8, 19), min_score=0.0)
    filtered = run_comparison(documents, approved, today=date(2026, 8, 19), min_score=0.9)

    assert len(filtered) <= len(all_signals)
    assert all(s.score >= 0.9 for s in filtered)


def test_scales_to_many_distinct_drugs_without_capping_result_count():
    from app.schemas.document import ApprovedIndication, Document

    documents = [
        Document(
            drug=f"drug-{i}",
            disease=f"disease-{i}",
            source="clinicaltrials",
            source_id=f"NCT-SCALE-{i}",
            phase="phase 2",
            date=date(2026, 1, 1),
        )
        for i in range(50)
    ]
    approved: list[ApprovedIndication] = []

    signals = run_comparison(documents, approved, today=date(2026, 8, 19))

    assert len(signals) == 50
    assert len({s.drug for s in signals}) == 50
