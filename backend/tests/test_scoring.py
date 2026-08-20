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


def test_fair_document_cap_prevents_one_drug_from_dominating():
    """A drug with far more raw documents than MAX_DOCUMENTS_PER_DRUG must
    not get a proportionally larger num_independent_sources/signal count
    advantage over a drug that stays under the cap — this is the
    2026-08-20 data-imbalance fix (see PROGRESS.md and
    scripts/clear_legacy_bulk_data.py)."""
    from app.core.scoring import apply_fair_document_cap
    from app.schemas.document import ApprovedIndication, Document

    cap = 10
    # "dominant-drug" has 5x the cap's worth of documents, all for the same
    # disease pairing, spread across distinct source_ids/dates.
    dominant_docs = [
        Document(
            drug="dominant-drug",
            disease="some disease",
            source="clinicaltrials",
            source_id=f"NCT-DOM-{i}",
            date=date(2026, 1, i % 27 + 1),
        )
        for i in range(cap * 5)
    ]
    # "fair-drug" stays right at the cap.
    fair_docs = [
        Document(
            drug="fair-drug",
            disease="some disease",
            source="clinicaltrials",
            source_id=f"NCT-FAIR-{i}",
            date=date(2026, 1, i % 27 + 1),
        )
        for i in range(cap)
    ]

    capped = apply_fair_document_cap(dominant_docs + fair_docs, max_per_drug=cap)
    dominant_kept = [d for d in capped if d.drug == "dominant-drug"]
    fair_kept = [d for d in capped if d.drug == "fair-drug"]

    assert len(dominant_kept) == cap
    assert len(fair_kept) == cap

    # run_comparison uses config's MAX_DOCUMENTS_PER_DRUG (not this test's
    # local `cap`) — build a dominant drug well past that default so the
    # real end-to-end cap actually engages, and confirm it stops the
    # dominant drug's supporting-document count from scaling past it.
    from app.core.config import MAX_DOCUMENTS_PER_DRUG

    huge_dominant_docs = [
        Document(
            drug="dominant-drug",
            disease="some disease",
            source="clinicaltrials",
            source_id=f"NCT-DOM-{i}",
            date=date(2026, 1, i % 27 + 1),
        )
        for i in range(MAX_DOCUMENTS_PER_DRUG * 3)
    ]
    small_fair_docs = fair_docs[: max(1, MAX_DOCUMENTS_PER_DRUG // cap)]

    approved: list[ApprovedIndication] = []
    signals = run_comparison(
        huge_dominant_docs + small_fair_docs, approved, today=date(2026, 8, 19), min_score=0.0
    )
    dominant_signal = next(s for s in signals if s.drug == "dominant-drug")
    assert len(dominant_signal.supporting_documents) == MAX_DOCUMENTS_PER_DRUG


def test_fair_document_cap_keeps_most_recent_documents():
    from app.core.scoring import apply_fair_document_cap
    from app.schemas.document import Document

    docs = [
        Document(
            drug="drug-x",
            disease="disease-x",
            source="clinicaltrials",
            source_id=f"NCT-{i}",
            date=date(2020, 1, 1 + i),
        )
        for i in range(5)
    ]
    capped = apply_fair_document_cap(docs, max_per_drug=2)

    assert len(capped) == 2
    kept_ids = {d.source_id for d in capped}
    assert kept_ids == {"NCT-3", "NCT-4"}  # the two most recent
