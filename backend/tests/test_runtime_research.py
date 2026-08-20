"""Tests for the case-specific runtime-research engine
(app/core/runtime_research.py). No network calls: the Europe PMC /
ClinicalTrials.gov / RxNav HTTP fetchers are monkeypatched or exercised via
their pure parsing helpers directly, so this suite stays fast and
deterministic like the rest of the backend tests.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.runtime_research import (
    _is_therapeutic_relationship,
    _parse_paper,
    _parse_trial,
    _validate_drug,
    filter_documents_by_valid_drug,
    generate_case_queries,
    run_runtime_case_research,
)
from app.schemas.case import ResearchMetadata
from app.schemas.document import Document


# --- query generation --------------------------------------------------


def test_queries_are_generated_from_case_fields_not_hardcoded():
    queries = generate_case_queries(
        primary_condition="Chronic Kidney Disease",
        comorbidities=["Hypertension"],
        current_medications=["Lisinopril"],
    )
    joined = " ".join(queries)
    assert "Chronic Kidney Disease" in joined
    assert "Hypertension" in joined
    assert "Lisinopril" in joined
    # nothing from the example case in the product brief should leak in —
    # checked case-insensitively (a prior real bug hardcoded lowercase
    # "diabetes drug" into every comorbidity query and a case-sensitive
    # "Diabetes" check here missed it entirely)
    assert "diabetes" not in joined.lower()
    assert "metformin" not in joined.lower()


def test_queries_are_deduplicated_and_multiple():
    queries = generate_case_queries("Heart Failure", ["Heart Failure"], [])
    assert len(queries) == len(set(queries))
    assert len(queries) > 1


# --- mention-only vs therapeutic relationship ---------------------------


def test_mere_cooccurrence_is_not_therapeutic():
    text = "Metformin is a biguanide. Diabetes affects many patients worldwide."
    assert not _is_therapeutic_relationship(text, "metformin", "diabetes")


def test_therapeutic_language_is_detected():
    text = "This trial investigated metformin as a treatment for diabetes outcomes."
    assert _is_therapeutic_relationship(text, "metformin", "diabetes")


def test_parse_paper_rejects_mention_only_as_document():
    paper = {
        "pmid": "12345",
        "title": "A survey of biguanides",
        "abstractText": "Metformin was mentioned. Separately, diabetes prevalence rose.",
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = _parse_paper(
        paper,
        query="metformin diabetes",
        targets=["diabetes"],
        case_drugs=["metformin"],
        metadata=metadata,
    )
    assert documents == []
    assert record is not None  # still cached for audit, with MENTION_ONLY relationship
    assert record.relationships[0]["status"] == "MENTION_ONLY"
    assert metadata.rejected_relationships
    assert metadata.rejected_relationships[0].evidence_type == "MENTION_ONLY"


def test_parse_paper_accepts_therapeutic_relationship_as_document():
    paper = {
        "pmid": "999",
        "title": "Randomized trial of metformin for diabetes treatment",
        "abstractText": "Metformin was administered and evaluated for diabetes treatment efficacy.",
        "firstPublicationDate": "2024-06-01",
    }
    metadata = ResearchMetadata()
    documents, record = _parse_paper(
        paper,
        query="metformin diabetes",
        targets=["diabetes"],
        case_drugs=["metformin"],
        metadata=metadata,
    )
    assert len(documents) == 1
    assert documents[0].drug == "metformin"
    assert documents[0].evidence_type != "MENTION_ONLY"
    assert record is not None


# --- drug validation ------------------------------------------------------


def test_junk_drug_names_are_rejected_without_hardcoding_snp_prs():
    rejected = {}
    cache = {}
    # placebo/procedure text is rejected by the junk filter, not a
    # hand-maintained "snp"/"prs" blocklist
    assert _validate_drug("Placebo Oral Tablet", source="clinicaltrials", rejected=rejected, resolver_cache=cache) is None
    assert rejected


def test_unresolved_candidate_is_rejected_when_rxnorm_has_no_match(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: None)
    rejected = {}
    cache = {}
    result = _validate_drug("Snp", source="europepmc", rejected=rejected, resolver_cache=cache)
    assert result is None
    assert any(r.reason == "no confident RxNorm resolution" for r in rejected.values())


def test_resolved_candidate_is_accepted(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "6809" if name == "metformin" else None)
    rejected = {}
    cache = {}
    result = _validate_drug("Metformin Hydrochloride", source="europepmc", rejected=rejected, resolver_cache=cache)
    assert result == "metformin"
    assert not rejected


# --- trial parsing: DRUG-type-only isn't sufficient on its own ------------


def test_trial_intervention_junk_is_rejected_even_when_typed_drug(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "123")
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT001", "briefTitle": "A study"},
            "conditionsModule": {"conditions": ["Diabetes"]},
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "DRUG", "name": "Placebo Comparator"},
                ]
            },
            "designModule": {},
            "statusModule": {},
        }
    }
    metadata = ResearchMetadata()
    rejected_drugs = {}
    cache = {}
    documents, record = _parse_trial(
        study,
        query="diabetes",
        targets=["diabetes"],
        metadata=metadata,
        rejected_drugs=rejected_drugs,
        resolver_cache=cache,
    )
    assert documents == []
    assert record is None


def test_trial_with_valid_drug_and_matching_condition_produces_document(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "6809")
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT002", "briefTitle": "Metformin in heart failure"},
            "conditionsModule": {"conditions": ["Heart Failure"]},
            "armsInterventionsModule": {
                "interventions": [{"type": "DRUG", "name": "Metformin"}]
            },
            "designModule": {"phases": ["PHASE2"]},
            "statusModule": {"studyFirstPostDateStruct": {"date": "2024-01-01"}},
        }
    }
    metadata = ResearchMetadata()
    documents, record = _parse_trial(
        study,
        query="heart failure metformin",
        targets=["heart failure"],
        metadata=metadata,
        rejected_drugs={},
        resolver_cache={},
    )
    assert len(documents) == 1
    assert documents[0].drug == "metformin"
    assert documents[0].source == "clinicaltrials"
    assert record is not None


# --- end-to-end (network mocked): no signal is an honest result -----------


class FakeSession:
    def add(self, *a, **k):
        pass

    def commit(self):
        pass


def _stub_all_sources_empty_success(monkeypatch):
    """Every source searches cleanly and finds nothing — the genuine
    "zero evidence" case, distinct from a source failure."""
    import app.core.runtime_research as rr

    monkeypatch.setattr(
        rr, "_fetch_papers_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[])
    )
    monkeypatch.setattr(
        rr, "_fetch_pubmed_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[])
    )
    monkeypatch.setattr(
        rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[])
    )
    monkeypatch.setattr(
        rr,
        "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )


def test_no_signal_case_returns_zero_candidates_with_metadata(monkeypatch):
    _stub_all_sources_empty_success(monkeypatch)

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Rare Disease XYZ",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
    )
    assert result.documents == []
    assert result.metadata.papers_retrieved == 0
    assert result.metadata.trials_retrieved == 0
    assert result.metadata.evidence_gaps  # explains why, doesn't fabricate
    assert result.metadata.used_local_fallback is False
    statuses = {s.source: s.status for s in result.metadata.source_statuses}
    assert statuses["europepmc"] == "no_results"
    assert statuses["clinicaltrials"] == "no_results"


def test_source_failure_is_recorded_not_fatal(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(
        rr,
        "_fetch_papers_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="timeout", error="timeout: boom"),
    )
    monkeypatch.setattr(
        rr, "_fetch_pubmed_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[])
    )
    monkeypatch.setattr(
        rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[])
    )
    monkeypatch.setattr(
        rr,
        "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Some Condition",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
    )
    assert any("Europe PMC" in gap for gap in result.metadata.evidence_gaps)
    # the failure is a structured status, not folded into "no evidence found"
    europepmc_status = next(s for s in result.metadata.source_statuses if s.source == "europepmc")
    assert europepmc_status.status == "timeout"
    assert not any("No relevant publications" in gap for gap in result.metadata.evidence_gaps)


# --- local-fallback document validation (Case #15 regression: "Snp"/"Prs")
#
# Real bug: the older discovery pipeline (app/ingestion/biorxiv.py's NER
# CHEMICAL-label extraction) stored genetics/statistics terms like "snp"
# (single nucleotide polymorphism) and "prs" (polygenic risk score) as if
# they were drugs, with no is_junk_drug_name/RxNorm gate applied at
# ingestion time — that gate only exists on this module's live-fetch path
# (_validate_drug). A case whose live research found zero papers/trials
# fell back to ALL local documents unfiltered, so "snp -> diabetes" and
# "prs -> diabetes" surfaced as real repurposing candidates in the UI.


def test_filter_documents_by_valid_drug_rejects_ner_artifacts(monkeypatch):
    import app.core.runtime_research as rr

    def fake_valid(name: str) -> bool:
        return name == "metformin"

    monkeypatch.setattr(rr, "is_valid_medication_entity", fake_valid)

    documents = [
        Document(drug="snp", disease="diabetes", source="medrxiv", source_id="doi1"),
        Document(drug="prs", disease="diabetes", source="medrxiv", source_id="doi1"),
        Document(drug="metformin", disease="heart failure", source="clinicaltrials", source_id="NCT1"),
    ]
    filtered = filter_documents_by_valid_drug(documents)
    assert [d.drug for d in filtered] == ["metformin"]


def test_filter_documents_by_valid_drug_keeps_all_when_all_valid(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "is_valid_medication_entity", lambda name: True)

    documents = [
        Document(drug="metformin", disease="heart failure", source="clinicaltrials", source_id="NCT1"),
        Document(drug="insulin", disease="heart failure", source="clinicaltrials", source_id="NCT2"),
    ]
    filtered = filter_documents_by_valid_drug(documents)
    assert len(filtered) == 2


# --- retrieval-layer audit: query broadening, cross-source dedup, and
# honest fallback semantics (API failure vs genuine zero results) ---------
#
# Real bug this section guards: a case whose primary_condition was a
# verbose ontology-style label ("Diabetes - Type 2 (adult, non-insulin-
# independent)") retrieved 0 raw items from Europe PMC/ClinicalTrials.gov
# — confirmed live (hitCount: 0) — purely because generate_case_queries'
# tier-1 queries quote that label as an exact phrase, which never appears
# verbatim in literature, even though "type 2 diabetes" has abundant real
# evidence. Broadening (generate_broad_case_queries) exists to retry with
# a less restrictive form before giving up.


def _paper(pmid: str, *, title: str = "Metformin treatment trial", drug: str = "metformin", disease: str = "heart failure") -> dict:
    return {
        "pmid": pmid,
        "doi": None,
        "source": "MED",
        "title": title,
        "abstractText": f"{drug} was administered and evaluated for {disease} treatment in this randomized trial.",
        "firstPublicationDate": "2024-01-01",
        "pubTypeList": {"pubType": ["Randomized Controlled Trial"]},
    }


def test_broadening_fires_when_tier1_finds_zero_raw_items(monkeypatch):
    import app.core.runtime_research as rr

    def papers_by_query(q, since):
        # Only the broadened (unquoted) form finds anything — mirrors the
        # real bug: tier-1's quoted exact-phrase queries find nothing.
        if '"' in q:
            return rr.QueryOutcome(query=q, status="success", items=[])
        return rr.QueryOutcome(query=q, status="success", items=[_paper("999", disease="diabetes")])

    monkeypatch.setattr(rr, "_fetch_papers_for_query_safe", papers_by_query)
    monkeypatch.setattr(rr, "_fetch_pubmed_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Diabetes - Type 2 (adult, non-insulin-independent)",
        comorbidities=[],
        current_medications=["Metformin"],
        local_approved=[],
    )
    assert result.metadata.broadened_queries  # tier-2 retry was attempted
    assert result.metadata.papers_retrieved == 1  # and it found the paper tier-1 missed
    assert result.documents and result.documents[0].drug == "metformin"


def test_broadening_does_not_fire_when_tier1_finds_raw_items(monkeypatch):
    """Tier-1 finding raw items but none passing relevance filtering is a
    different, legitimate outcome ("retrieved but not relevant evidence")
    — broadening again wouldn't fix mismatched entities and shouldn't be
    attempted."""
    import app.core.runtime_research as rr

    unrelated_paper = {
        "pmid": "1",
        "doi": None,
        "source": "MED",
        "title": "Unrelated topic",
        "abstractText": "This paper is about something else entirely.",
        "firstPublicationDate": "2024-01-01",
        "pubTypeList": {"pubType": []},
    }
    monkeypatch.setattr(
        rr, "_fetch_papers_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="success", items=[unrelated_paper]),
    )
    monkeypatch.setattr(rr, "_fetch_pubmed_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=["Metformin"],
        local_approved=[],
    )
    assert result.metadata.broadened_queries == []


def test_europepmc_and_pubmed_duplicate_papers_are_deduplicated(monkeypatch):
    """Same PMID returned by both Europe PMC and PubMed must count once,
    not twice — this is what makes adding PubMed safe without inflating
    evidence-strength scoring (independent-mention counting in scoring.py
    trusts document counts to reflect independent sources)."""
    import app.core.runtime_research as rr

    shared_paper = _paper("555")
    monkeypatch.setattr(
        rr, "_fetch_papers_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="success", items=[shared_paper]),
    )
    monkeypatch.setattr(
        rr, "_fetch_pubmed_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="success", items=[shared_paper]),
    )
    monkeypatch.setattr(rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=["Metformin"],
        local_approved=[],
    )
    assert result.metadata.papers_retrieved == 1
    assert len(result.documents) == 1


def test_local_fallback_after_hard_source_failure_explains_why(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "is_valid_medication_entity", lambda name: True)
    monkeypatch.setattr(
        rr, "_fetch_papers_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="timeout", error="timeout: boom"),
    )
    monkeypatch.setattr(
        rr, "_fetch_pubmed_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="timeout", error="timeout: boom"),
    )
    monkeypatch.setattr(
        rr, "_fetch_trials_for_query_safe",
        lambda q: rr.QueryOutcome(query=q, status="timeout", error="timeout: boom"),
    )
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    local_documents = [
        Document(drug="metformin", disease="heart failure", source="clinicaltrials", source_id="NCT-LOCAL"),
    ]

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        local_documents=local_documents,
    )
    assert result.metadata.used_local_fallback is True
    assert "unavailable" in result.metadata.local_fallback_reason.lower()
    assert result.documents and result.documents[0].drug == "metformin"


def test_local_fallback_after_genuine_zero_results_explains_why(monkeypatch):
    _stub_all_sources_empty_success(monkeypatch)
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "is_valid_medication_entity", lambda name: True)

    local_documents = [
        Document(drug="metformin", disease="heart failure", source="clinicaltrials", source_id="NCT-LOCAL"),
    ]

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        local_documents=local_documents,
    )
    assert result.metadata.used_local_fallback is True
    assert "found no case-relevant" in result.metadata.local_fallback_reason.lower()


def test_local_fallback_not_used_when_nothing_relevant_or_valid(monkeypatch):
    """Genuine zero-signal case: live search found nothing, and whatever
    is in the local cache is either not disease-relevant or not a
    validated drug — must NOT silently substitute unrelated local data."""
    _stub_all_sources_empty_success(monkeypatch)
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "is_valid_medication_entity", lambda name: False)

    local_documents = [
        Document(drug="snp", disease="heart failure", source="medrxiv", source_id="doi1"),
        Document(drug="metformin", disease="completely unrelated disease", source="clinicaltrials", source_id="NCT-X"),
    ]

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        local_documents=local_documents,
    )
    assert result.metadata.used_local_fallback is False
    assert result.metadata.local_fallback_reason is None
    assert result.documents == []
