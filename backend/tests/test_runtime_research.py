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
    generate_broad_case_queries,
    generate_case_queries,
    run_runtime_case_research,
)
from app.schemas.case import ResearchMetadata
from app.schemas.document import Document


# --- query generation --------------------------------------------------


def test_queries_are_generated_from_case_fields_not_hardcoded():
    plan = generate_case_queries(
        primary_condition="Chronic Kidney Disease",
        comorbidities=["Hypertension"],
        current_medications=["Lisinopril"],
    )
    joined = " ".join(entry.query for entry in plan)
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
    plan = generate_case_queries("Heart Failure", ["Heart Failure"], [])
    queries = [entry.query for entry in plan]
    assert len(queries) == len(set(queries))
    assert len(queries) > 1


# --- attribute-aware query generation (patient-context Phase 2) --------


def _core_three_field_plan():
    return generate_case_queries(
        primary_condition="Type 2 Diabetes",
        comorbidities=["Heart Failure"],
        current_medications=["Metformin"],
    )


def test_existing_three_field_case_generates_same_core_queries_as_before():
    """A case supplying only the original three fields must produce
    exactly the query text the old (pre-Phase-2) generator produced —
    proves the richer-attribute plumbing is purely additive."""
    plan = _core_three_field_plan()
    queries = {entry.query for entry in plan}
    assert queries == {
        '"Type 2 Diabetes" drug repurposing',
        '"Type 2 Diabetes" clinical trial',
        '"Type 2 Diabetes" alternative indication',
        '"Type 2 Diabetes" "Heart Failure"',
        '"Heart Failure" "Type 2 Diabetes" drug',
        '"Heart Failure" drug treatment',
        '"Heart Failure" clinical trial',
        '"Metformin" "Type 2 Diabetes"',
        '"Metformin" alternative indication',
        '"Metformin" therapeutic effect "Type 2 Diabetes"',
        '"Metformin" "Heart Failure"',
        '"Metformin" therapeutic effect "Heart Failure"',
    }
    # Every one of these core queries is tier 1 and reaches all three
    # sources, exactly as before this phase.
    assert all(entry.tier == 1 for entry in plan)
    assert all(set(entry.sources) == {"europepmc", "pubmed", "clinicaltrials"} for entry in plan)


def test_disease_subtype_influences_queries():
    base_queries = {entry.query for entry in _core_three_field_plan()}
    plan = generate_case_queries(
        primary_condition="Type 2 Diabetes",
        comorbidities=["Heart Failure"],
        current_medications=["Metformin"],
        disease_subtype="insulin-resistant",
    )
    queries = {entry.query for entry in plan}
    assert queries - base_queries  # subtype added genuinely new queries
    assert any("insulin-resistant" in entry.query for entry in plan)
    subtype_entries = [entry for entry in plan if "disease_subtype" in entry.attributes]
    assert subtype_entries
    assert all(entry.tier == 1 for entry in subtype_entries)


def test_phenotypes_influence_queries():
    plan = generate_case_queries(
        primary_condition="Alzheimer's Disease",
        comorbidities=[],
        current_medications=["Metformin"],
        phenotypes=["Cognitive Decline"],
    )
    phenotype_entries = [entry for entry in plan if "phenotypes" in entry.attributes]
    assert phenotype_entries
    assert any("Cognitive Decline" in entry.query for entry in phenotype_entries)
    # Example from the product brief: primary + phenotype + medication.
    assert any(
        "Alzheimer's Disease" in entry.query and "Metformin" in entry.query and "Cognitive Decline" in entry.query
        for entry in phenotype_entries
    )


def test_biomarkers_can_influence_queries():
    plan = generate_case_queries(
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        biomarkers=[{"name": "BRCA1", "value": "positive"}],
    )
    biomarker_entries = [entry for entry in plan if "biomarkers" in entry.attributes]
    assert biomarker_entries
    assert any("BRCA1" in entry.query for entry in biomarker_entries)
    assert all(entry.tier == 3 for entry in biomarker_entries)
    # Biomarkers can inform trial eligibility text (e.g. "HER2-positive"
    # trial titles), so they reach ClinicalTrials.gov too.
    assert any("clinicaltrials" in entry.sources for entry in biomarker_entries)


def test_previous_treatment_response_influences_refractory_queries():
    plan = generate_case_queries(
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        previous_treatments=[{"name": "Tamoxifen", "response": "no response"}],
    )
    treatment_entries = [entry for entry in plan if "previous_treatments" in entry.attributes]
    assert treatment_entries
    assert any("refractory" in entry.query.lower() or "resistant" in entry.query.lower() for entry in treatment_entries)


def test_previous_treatment_without_negative_response_is_not_phrased_as_refractory():
    plan = generate_case_queries(
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        previous_treatments=[{"name": "Tamoxifen"}],
    )
    treatment_entries = [entry for entry in plan if "previous_treatments" in entry.attributes]
    assert treatment_entries
    assert not any("refractory" in entry.query.lower() for entry in treatment_entries)
    assert any("prior treatment" in entry.query for entry in treatment_entries)


def test_genetic_markers_are_restricted_to_literature_sources():
    plan = generate_case_queries(
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        genetic_markers=[{"gene": "BRCA1", "variant": "c.68_69delAG"}],
    )
    genetic_entries = [entry for entry in plan if "genetic_markers" in entry.attributes]
    assert genetic_entries
    for entry in genetic_entries:
        assert "clinicaltrials" not in entry.sources
        assert set(entry.sources) <= {"europepmc", "pubmed"}


def test_demographic_fields_do_not_create_malformed_queries_and_skip_clinicaltrials():
    plan = generate_case_queries(
        primary_condition="Alzheimer's Disease",
        comorbidities=[],
        current_medications=[],
        age_group="older adult",
        sex="female",
        disease_stage="moderate",
        disease_duration="8 years",
    )
    tier2_entries = [entry for entry in plan if entry.tier == 2]
    assert tier2_entries
    for entry in tier2_entries:
        assert entry.query.strip() == entry.query
        assert "  " not in entry.query  # no double-spaces from empty-field concatenation
        assert "None" not in entry.query
        # population/context refinements are literature-only (see
        # generate_case_queries' source-routing rationale).
        assert "clinicaltrials" not in entry.sources
    # Product-brief example: primary + stage + medication.
    plan_with_med = generate_case_queries(
        primary_condition="Alzheimer's Disease",
        comorbidities=[],
        current_medications=["Metformin"],
        disease_stage="moderate",
    )
    assert any(
        "Alzheimer's Disease" in entry.query and "moderate" in entry.query and "Metformin" in entry.query
        for entry in plan_with_med
    )


def test_empty_optional_fields_are_ignored():
    plan_with_blanks = generate_case_queries(
        primary_condition="Heart Failure",
        comorbidities=[],
        current_medications=[],
        disease_subtype="",
        phenotypes=["", "   "],
        age_group=None,
        sex="",
        disease_stage=None,
        disease_duration="",
        biomarkers=[{"name": ""}, {"name": "  "}],
        genetic_markers=[{"gene": ""}],
        previous_treatments=[{"name": ""}],
    )
    plan_without = generate_case_queries(
        primary_condition="Heart Failure", comorbidities=[], current_medications=[]
    )
    assert {e.query for e in plan_with_blanks} == {e.query for e in plan_without}


def test_query_count_remains_bounded():
    """A moderately rich profile (a couple entries per list attribute)
    should not blow up into hundreds of queries — controlled volume per
    the tiering strategy, not a combinatorial explosion across every
    attribute."""
    plan = generate_case_queries(
        primary_condition="Alzheimer's Disease",
        comorbidities=["Type 2 Diabetes", "Hypertension"],
        current_medications=["Metformin", "Lisinopril"],
        disease_subtype="early-onset",
        phenotypes=["Cognitive Decline", "Memory Loss"],
        age_group="older adult",
        sex="female",
        disease_stage="moderate",
        disease_duration="5 years",
        biomarkers=[{"name": "APOE4", "value": "positive"}],
        genetic_markers=[{"gene": "APOE", "variant": "e4"}],
        previous_treatments=[{"name": "Donepezil", "response": "no response"}],
    )
    assert len(plan) < 80


def test_no_hardcoded_disease_or_drug_names_are_introduced():
    """Every generated query must trace back to case input text — nothing
    from any other example case (e.g. this file's other fixtures) should
    leak into an unrelated case's query set."""
    plan = generate_case_queries(
        primary_condition="Glorbnitis Syndrome Type IX",
        comorbidities=["Zephyrian Fever"],
        current_medications=["Quixotane"],
        disease_subtype="Blorptic Variant",
        phenotypes=["Zorptic Fatigue"],
        biomarkers=[{"name": "ZQ9", "value": "elevated"}],
        genetic_markers=[{"gene": "ZQG1"}],
        previous_treatments=[{"name": "Fablutrex", "response": "refractory"}],
    )
    joined = " ".join(entry.query for entry in plan).lower()
    for leaked_term in ("diabetes", "metformin", "alzheimer", "breast cancer", "brca1", "heart failure"):
        assert leaked_term not in joined


def test_broadening_folds_in_disease_subtype():
    """generate_broad_case_queries includes a broadened subtype combo
    (same verbose-label risk as primary_condition), without fanning out
    into a second full query set."""
    plan = generate_broad_case_queries(
        "Diabetes - Type 2 (adult, non-insulin-independent)",
        [],
        ["Metformin"],
        disease_subtype="Insulin Resistant (severe)",
    )
    assert all(entry.tier == 0 for entry in plan)
    assert any("insulin resistant" in entry.query.lower() for entry in plan)
    assert any("disease_subtype" in entry.attributes for entry in plan)


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
        target_tokens=frozenset({"diabetes"}),
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
        target_tokens=frozenset({"diabetes"}),
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


# --- end-to-end: instrumentation + broadening/failure semantics with the
# richer patient-context attributes wired through run_runtime_case_research


def test_query_plan_instrumentation_records_tier_source_and_attributes(monkeypatch):
    """metadata.query_plan carries one (tier, source, query, attributes)
    record per dispatched query — enough to determine which patient
    attributes contributed to retrieval for this case."""
    _stub_all_sources_empty_success(monkeypatch)

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        disease_subtype="triple-negative",
        biomarkers=[{"name": "BRCA1", "value": "positive"}],
    )
    plan = result.metadata.query_plan
    assert plan
    assert all(hasattr(entry, "tier") and hasattr(entry, "source") for entry in plan)
    assert any("disease_subtype" in entry.attributes for entry in plan)
    assert any("biomarkers" in entry.attributes for entry in plan)
    # Every entry's source is one it was actually dispatched to.
    assert all(entry.source in ("europepmc", "pubmed", "clinicaltrials") for entry in plan)
    # Genetic-marker-only routing isn't exercised here (no genetic markers
    # supplied), but biomarker entries should include clinicaltrials.
    biomarker_sources = {entry.source for entry in plan if "biomarkers" in entry.attributes}
    assert "clinicaltrials" in biomarker_sources


def test_broadening_still_occurs_with_richer_attributes_present(monkeypatch):
    """The zero-raw-hit broadening retry still fires when a case carries
    the new richer attributes, not just the original three fields."""
    import app.core.runtime_research as rr

    def papers_by_query(q, since):
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
        disease_subtype="Insulin Resistant (severe)",
        phenotypes=["Fatigue"],
    )
    assert result.metadata.broadened_queries
    assert result.metadata.papers_retrieved == 1


def test_api_failure_and_zero_results_remain_distinguishable_with_richer_attributes(monkeypatch):
    """Adding literature-only query routing (population/genetic-marker
    queries) must not blur the existing "hard failure" vs "clean zero
    results" distinction for any source's aggregate status."""
    import app.core.runtime_research as rr

    monkeypatch.setattr(
        rr, "_fetch_papers_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="timeout", error="timeout: boom"),
    )
    monkeypatch.setattr(
        rr, "_fetch_pubmed_for_query_safe",
        lambda q, since: rr.QueryOutcome(query=q, status="success", items=[]),
    )
    monkeypatch.setattr(
        rr, "_fetch_trials_for_query_safe",
        lambda q: rr.QueryOutcome(query=q, status="success", items=[]),
    )
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        age_group="older adult",
        genetic_markers=[{"gene": "BRCA1"}],
    )
    statuses = {s.source: s.status for s in result.metadata.source_statuses}
    # europepmc hard-failed on every query it received (including the
    # literature-only age_group/genetic_marker queries) -- never silently
    # reported as "no_results".
    assert statuses["europepmc"] == "timeout"
    assert statuses["pubmed"] == "no_results"
    assert statuses["clinicaltrials"] == "no_results"
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


# --- Phase 3: publication drug-candidate discovery (fixes the "0 papers"
# bug Phase 2 live verification exposed) ------------------------------
#
# Root cause: `_parse_paper` only ever checked a paper's text for the
# case's own current medications (`case_drugs`) — it had no way to
# discover a NEW drug the paper itself names. A case with no current
# medications (e.g. Breast Cancer alone) could never produce a single
# publication document, no matter how relevant the retrieved literature
# was, purely because there was nothing in `case_drugs` to match against.
# `_discover_paper_drugs` fixes this by extracting a small, bounded set of
# candidate terms from the same disease+therapeutic-language-qualifying
# sentences and validating each one through the existing RxNorm-backed
# `_validate_drug` gate — never a new/weaker check.


def test_legitimate_therapeutic_paper_survives_without_case_medication(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "999001" if name == "capecitabine" else None)

    paper = {
        "pmid": "111",
        "title": "Capecitabine in triple-negative breast cancer",
        "abstractText": (
            "Capecitabine was administered as adjuvant treatment and improved outcomes in "
            "patients with breast cancer in this randomized trial."
        ),
        "firstPublicationDate": "2024-01-01",
        "pubTypeList": {"pubType": ["Randomized Controlled Trial"]},
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],  # no current medications -- the exact bug scenario
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents
    assert any(d.drug == "capecitabine" and d.disease == "breast cancer" for d in documents)
    assert record is not None


def test_unrelated_or_incidental_paper_is_still_filtered(monkeypatch):
    """A real, RxNorm-resolvable drug mentioned only incidentally (not in
    a therapeutic sentence about the target disease) must still be
    filtered out — discovery doesn't relax the therapeutic-language gate."""
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "1" if name == "aspirin" else None)

    paper = {
        "pmid": "222",
        "title": "Aspirin pharmacology overview",
        "abstractText": "Aspirin is a common analgesic. Breast cancer incidence varies by region.",
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents == []


def test_gene_only_evidence_is_rejected_as_drug_candidate(monkeypatch):
    import app.core.runtime_research as rr

    calls: list[str] = []
    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: calls.append(name) or None)

    paper = {
        "pmid": "333",
        "title": "BRCA1 mutation and breast cancer treatment response",
        "abstractText": (
            "Patients harboring a BRCA1 mutation were evaluated for treatment response "
            "in this breast cancer cohort."
        ),
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents == []
    # gene-shaped tokens (letters+digits, e.g. "brca1") never even reach
    # the RxNorm-validation gate.
    assert "brca1" not in calls


def test_biomarker_only_evidence_is_not_treated_as_drug(monkeypatch):
    import app.core.runtime_research as rr

    calls: list[str] = []
    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: calls.append(name) or None)

    paper = {
        "pmid": "444",
        "title": "HER2 status and breast cancer treatment outcomes",
        "abstractText": (
            "HER2-positive status was associated with treatment outcomes in this breast "
            "cancer trial."
        ),
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents == []
    assert "her2" not in calls


def test_placebo_mention_remains_rejected(monkeypatch):
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: None)

    paper = {
        "pmid": "555",
        "title": "Placebo-controlled trial in breast cancer",
        "abstractText": "Placebo was administered and evaluated for breast cancer treatment response.",
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents == []


def test_disease_normalization_still_matches_staged_disease_mentions(monkeypatch):
    """The new discovery path rides on the same disease_matching logic as
    before — a staged/qualified disease mention in the paper still matches
    the case's plain target term."""
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "999003" if name == "olaparib" else None)

    paper = {
        "pmid": "777",
        "title": "Olaparib in Stage III Breast Cancer",
        "abstractText": "Olaparib was administered and evaluated for Stage III breast cancer treatment response.",
        "firstPublicationDate": "2024-01-01",
    }
    metadata = ResearchMetadata()
    documents, record = rr._parse_paper(
        paper,
        query="breast cancer",
        targets=["breast cancer"],
        case_drugs=[],
        metadata=metadata,
        target_tokens=frozenset({"breast", "cancer"}),
        rejected_drugs={},
        resolver_cache={},
    )
    assert documents and documents[0].drug == "olaparib"


def test_known_indication_for_paper_discovered_drug_remains_excluded_from_candidates(monkeypatch):
    """A drug discovered directly from paper text (not a case medication)
    that's already approved for the exact matched disease must still be
    excluded from repurposing candidates by the existing known-indication
    logic (app.core.scoring.is_already_approved) — unaffected by
    discovering it from free text instead of case_drugs."""
    import app.core.runtime_research as rr
    from app.core.case_analysis import analyze_case
    from app.schemas.document import ApprovedIndication

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "999002" if name == "capecitabine" else None)

    def papers_by_query(q, since):
        return rr.QueryOutcome(
            query=q,
            status="success",
            items=[
                {
                    "pmid": "666",
                    "doi": None,
                    "source": "MED",
                    "title": "Capecitabine for breast cancer",
                    "abstractText": "Capecitabine was administered and evaluated for breast cancer treatment.",
                    "firstPublicationDate": "2024-01-01",
                    "pubTypeList": {"pubType": ["Journal Article"]},
                }
            ],
        )

    monkeypatch.setattr(rr, "_fetch_papers_for_query_safe", papers_by_query)
    monkeypatch.setattr(rr, "_fetch_pubmed_for_query_safe", lambda q, since: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(rr, "_fetch_trials_for_query_safe", lambda q: rr.QueryOutcome(query=q, status="success", items=[]))
    monkeypatch.setattr(
        rr, "_fetch_openfda_indications",
        lambda session, drugs, metadata: ([], rr.SourceAttempt(source="openfda", status="not_attempted")),
    )

    approved = [ApprovedIndication(drug="capecitabine", disease="breast cancer", source="openfda", source_id="LBL1")]

    result = run_runtime_case_research(
        FakeSession(),
        case_id=1,
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        local_approved=approved,
    )
    # Still retrieved as raw evidence (research_metadata should be able to
    # show it was found and why it was excluded)...
    assert any(d.drug == "capecitabine" for d in result.documents)
    assert any(
        r.drug == "capecitabine" and r.reason == "known indication, not a repurposing candidate"
        for r in result.metadata.rejected_relationships
    )

    # ...but never surfaced as a repurposing candidate.
    candidates = analyze_case(
        primary_condition="Breast Cancer",
        comorbidities=[],
        documents=result.documents,
        approved=result.approved_indications,
    )
    assert not any(c.drug == "capecitabine" for c in candidates)


def test_enriched_attributes_reach_retrieval_and_paper_discovered_drug_survives(monkeypatch):
    """End-to-end: the enriched Breast Cancer case from live verification
    (subtype + phenotype + biomarker, no current medication) now produces
    a real publication candidate, and the query instrumentation shows the
    biomarker attribute contributed to the query that found it."""
    import app.core.runtime_research as rr

    monkeypatch.setattr(rr, "resolve_rxnorm_id", lambda name: "999004" if name == "olaparib" else None)

    def papers_by_query(q, since):
        if "brca1" in q.lower():
            return rr.QueryOutcome(
                query=q,
                status="success",
                items=[
                    {
                        "pmid": "888",
                        "doi": None,
                        "source": "MED",
                        "title": "Olaparib in BRCA1-positive triple-negative breast cancer",
                        "abstractText": "Olaparib was administered and evaluated for treatment-resistant breast cancer.",
                        "firstPublicationDate": "2024-01-01",
                        "pubTypeList": {"pubType": ["Journal Article"]},
                    }
                ],
            )
        return rr.QueryOutcome(query=q, status="success", items=[])

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
        primary_condition="Breast Cancer",
        comorbidities=[],
        current_medications=[],
        local_approved=[],
        disease_subtype="Triple-negative",
        phenotypes=["Treatment-resistant"],
        biomarkers=[{"name": "BRCA1", "value": "positive"}],
    )
    assert any("biomarkers" in e.attributes for e in result.metadata.query_plan)
    assert any(d.drug == "olaparib" and d.disease == "breast cancer" for d in result.documents)
