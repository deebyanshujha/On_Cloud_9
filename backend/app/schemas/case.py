"""TheraLens Case + case-analysis API shapes.

Response language deliberately avoids any prescriptive/treatment-decision
phrasing ("take X", "X is the best treatment") — field names and generated
text use research-framing language instead ("potential research signal",
"evidence suggests", "candidate for further investigation", "clinical
review required", "insufficient evidence"). This is baked into the field
names themselves, not left as a frontend-formatting concern.
"""
from __future__ import annotations

from datetime import date as date_, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ConflictState = Literal["conflict_detected", "no_conflict_detected", "insufficient_evidence"]


class PreviousTreatmentInput(BaseModel):
    """One previous treatment, with an optional recorded response (e.g.
    'no response', 'partial', 'relapsed'). Free-text, dynamic — no
    hardcoded drug/response list. Same shape used for both request input
    and response output (no server-computed fields needed yet)."""

    name: str
    response: Optional[str] = None


class BiomarkerInput(BaseModel):
    """One biomarker/lab result, with an optional value (e.g.
    name='HER2', value='positive'). Free-text, dynamic."""

    name: str
    value: Optional[str] = None


class GeneticMarkerInput(BaseModel):
    """One genetic/pharmacogenomic finding (e.g. gene='BRCA1',
    variant='c.68_69delAG'). Free-text, dynamic."""

    gene: str
    variant: Optional[str] = None
    note: Optional[str] = None


class CaseCreate(BaseModel):
    primary_condition: str
    comorbidities: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)

    # Richer patient-context fields (all optional — a request containing
    # only primary_condition/comorbidities/current_medications continues to
    # work unchanged). Not yet surfaced in the UI; this establishes the
    # schema/data-model support only.
    age_group: Optional[str] = None
    sex: Optional[str] = None
    disease_stage: Optional[str] = None
    disease_subtype: Optional[str] = None
    disease_duration: Optional[str] = None
    phenotypes: list[str] = Field(default_factory=list)
    previous_treatments: list[PreviousTreatmentInput] = Field(default_factory=list)
    biomarkers: list[BiomarkerInput] = Field(default_factory=list)
    genetic_markers: list[GeneticMarkerInput] = Field(default_factory=list)

    allow_duplicate: bool = Field(
        default=False,
        description="If false (default) and an existing case has the exact "
        "same primary condition + comorbidity set + medication set, that "
        "existing case is returned instead of creating a lookalike "
        "duplicate. Set true to explicitly create a separate case anyway.",
    )


class CaseUpdate(BaseModel):
    saved: bool


class CaseOut(BaseModel):
    id: int
    primary_condition: str
    comorbidities: list[str]
    current_medications: list[str]

    # Richer patient-context fields — see CaseCreate. Default to
    # None/empty so a case created before this phase still validates and
    # returns cleanly.
    age_group: Optional[str] = None
    sex: Optional[str] = None
    disease_stage: Optional[str] = None
    disease_subtype: Optional[str] = None
    disease_duration: Optional[str] = None
    phenotypes: list[str] = Field(default_factory=list)
    previous_treatments: list[PreviousTreatmentInput] = Field(default_factory=list)
    biomarkers: list[BiomarkerInput] = Field(default_factory=list)
    genetic_markers: list[GeneticMarkerInput] = Field(default_factory=list)

    saved: bool
    created_at: datetime


class CaseSummaryOut(CaseOut):
    """List-view shape (Phase 2 frontend: Dashboard, Cases nav). Adds a
    cheap summary of the case's last analysis, if any, read straight off
    the stored analysis JSON — no recomputation, same "read layer" pattern
    as everything else in this API."""

    last_analyzed_at: Optional[datetime] = None
    candidate_count: Optional[int] = None
    conflict_count: Optional[int] = Field(
        default=None,
        description="Number of candidates with at least one "
        "'conflict_detected' comorbidity check in the last analysis.",
    )
    top_research_priority_score: Optional[float] = None
    has_new_evidence: Optional[bool] = Field(
        default=None,
        description="From the last time 'Re-check for new evidence' was run "
        "for this case (manually triggered — see POST /cases/{id}/recheck "
        "and POST /cases/recheck-all). null if never checked.",
    )
    evidence_checked_at: Optional[datetime] = None


class SupportingEvidence(BaseModel):
    """One real supporting document (trial, preprint) behind a candidate's
    disease association — never fabricated, always traceable to a real
    source_id/url already ingested by the existing pipeline."""

    source: str
    source_id: str
    url: str | None
    date: date_ | None
    phase: str | None
    evidence_type: Optional[str] = None


class ComorbidityCheck(BaseModel):
    comorbidity: str
    status: ConflictState
    evidence: Optional[str] = Field(
        default=None,
        description="Verbatim excerpt from the candidate drug's real openFDA "
        "contraindications/warnings text. Populated only when status is "
        "'conflict_detected'.",
    )


class CurrentMedicationInteractionNote(BaseModel):
    """Per-scope-decision (see PROGRESS.md): v1 does not attempt
    current-medication pairwise drug-drug interaction checking. This is
    always returned, never silently omitted, so callers can't mistake
    'not checked' for 'checked and clear'."""

    status: Literal["insufficient_interaction_data_available"] = (
        "insufficient_interaction_data_available"
    )
    note: str = (
        "Current-medication drug-drug interaction checking is out of scope "
        "for this phase. Verified interaction data would require one drug's "
        "label to explicitly name the other; that check is deferred, not "
        "silently skipped. Clinical review required for interaction "
        "assessment."
    )


class PatientContextCheck(BaseModel):
    """One check of whether a candidate's supporting evidence actually
    addresses a specific patient-context attribute (e.g. disease subtype,
    a biomarker, a prior-treatment response) — distinct from
    ComorbidityCheck, which checks drug-label safety text, not evidence
    relevance. Three-state, same non-conflation-of-absence-with-negative
    rule as ComorbidityCheck.

    Relevance-checking logic is not implemented yet (see PROGRESS.md) —
    this schema only establishes the contract; `CandidateOut.
    patient_context_checks` defaults to an empty list until that logic
    lands."""

    attribute: str = Field(
        description="Which patient-context attribute this check is about, "
        "e.g. 'disease_subtype', 'biomarker:HER2', "
        "'prior_treatment:metformin'."
    )
    status: Literal[
        "relevance_confirmed", "not_addressed_in_evidence", "insufficient_evidence"
    ]
    evidence: Optional[str] = Field(
        default=None,
        description="Verbatim excerpt from real supporting evidence, "
        "populated only when status is 'relevance_confirmed' — never "
        "fabricated, same rule as ComorbidityCheck.evidence.",
    )


class LLMInterpretation(BaseModel):
    """Phase 4: an optional, additive interpretation of one candidate's
    already-computed evidence (see app/core/llm_interpreter.py). The LLM
    (Google Gemini — see PROGRESS.md's Phase 4 entry for why this isn't
    Anthropic's Claude despite the field/module naming predating the
    switch) is given only the structured fields already on this
    CandidateOut (reasoning_trail, comorbidity_checks, known_indications,
    evidence tier/scores) and instructed never to introduce a new drug,
    disease, or claim beyond that evidence — it restates/explains, it does
    not discover. Absent (None) whenever the LLM layer is not configured,
    disabled, or the call/parse failed; never fabricated as a fallback."""

    summary: str = Field(
        description="The model's plain-language interpretation of this "
        "candidate's evidence, grounded only in the structured evidence "
        "already computed by the deterministic pipeline."
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Caveats/limitations the model flagged while "
        "interpreting this evidence, e.g. sparse evidence or an unresolved "
        "comorbidity conflict.",
    )
    model: str
    generated_at: datetime


class CandidateOut(BaseModel):
    """One repurposing candidate surfaced for this case's primary condition,
    as a research signal — never a recommendation."""

    drug: str
    disease: str = Field(
        description="The case-relevant disease/condition this drug is being "
        "studied for."
    )
    research_priority_score: float
    evidence_strength_score: float = Field(
        description="The underlying repurposing-signal score from the "
        "existing scoring engine (app/core/scoring.py), before any "
        "case-context adjustment."
    )
    known_indications: list[str] = Field(
        description="What this drug is already FDA-approved for, per "
        "ingested openFDA label text."
    )
    evidence_tier: str = Field(
        description="One of 'high'/'moderate'/'low'/'insufficient' — same "
        "thresholds as app.core.case_analysis.evidence_tier and "
        "frontend/src/scoring.ts's scoreTier, kept in sync so the tier "
        "shown never disagrees across the app."
    )
    evidence_tier_reason: str = Field(
        description="Short, human-readable basis for the tier, built from "
        "real supporting-evidence counts (e.g. '3 clinical trials, 2 "
        "publications') — never a fabricated explanation."
    )
    primary_condition_evidence: list[SupportingEvidence]
    comorbidity_checks: list[ComorbidityCheck]
    patient_context_checks: list[PatientContextCheck] = Field(
        default_factory=list,
        description="Evidence-vs-patient-attribute relevance checks (see "
        "PatientContextCheck). Always empty for now — the relevance-"
        "checking logic that populates this is a later phase; this field "
        "only establishes the contract.",
    )
    current_medication_interactions: CurrentMedicationInteractionNote
    reasoning_trail: list[str] = Field(
        description="Ordered, human-readable trail: known indication -> new "
        "disease association -> supporting studies/trials -> evidence "
        "strength -> context check result -> final research priority score."
    )
    research_framing: str = (
        "Potential research signal — evidence suggests further investigation "
        "may be warranted. Not a treatment recommendation."
    )
    llm_interpretation: Optional[LLMInterpretation] = Field(
        default=None,
        description="Optional LLM-generated plain-language restatement "
        "of this candidate's evidence (see LLMInterpretation). None "
        "whenever the LLM layer is unconfigured, disabled, or failed — "
        "the candidate itself is always complete and usable without it.",
    )


class RejectedDrug(BaseModel):
    raw_name: str
    normalized_name: Optional[str] = None
    reason: str
    source: Optional[str] = None


class RejectedRelationship(BaseModel):
    drug: Optional[str] = None
    disease: Optional[str] = None
    source: str
    source_id: str
    evidence_type: str
    reason: str


class SourceAttempt(BaseModel):
    """Structured per-source retrieval outcome for one case run — the
    difference between "searched and found nothing" and "the request
    failed" that a flat evidence_gaps string can't reliably convey. One
    entry per source (europepmc, pubmed, clinicaltrials, openfda) per run,
    aggregated across every query attempted against that source this run."""

    source: str
    status: Literal[
        "success",
        "no_results",
        "timeout",
        "http_error",
        "parse_error",
        "rate_limited",
        "not_attempted",
    ]
    results_found: int = 0
    queries_attempted: int = 0
    error: Optional[str] = None


class QueryPlanEntryOut(BaseModel):
    """One (query, source) dispatch record from the case-research query
    planner (see app.core.runtime_research.generate_case_queries) — lets a
    caller determine which patient-context attributes actually contributed
    to a query, and via which source it was searched. `tier` follows the
    query-generation tiers (1=core clinical context, 2=population/context
    refinement, 3=specialized evidence), with 0 reserved for a broadened
    zero-hit-retry query (see ResearchMetadata.broadened_queries)."""

    tier: int
    source: str
    query: str
    attributes: list[str] = Field(
        default_factory=list,
        description="Which case attributes contributed to this query, e.g. "
        "['primary_condition', 'disease_subtype'].",
    )


class ResearchMetadata(BaseModel):
    queries: list[str] = Field(default_factory=list)
    query_plan: list[QueryPlanEntryOut] = Field(
        default_factory=list,
        description="Structured per-(query, source) instrumentation for "
        "every query this run generated — see QueryPlanEntryOut. Lets a "
        "caller determine which patient-context attributes contributed to "
        "the evidence retrieved for a case.",
    )
    broadened_queries: list[str] = Field(
        default_factory=list,
        description="Second-tier, less-restrictive queries actually run "
        "because the first-tier exact-phrase queries came back with zero "
        "results from every live source — not a fixed part of every run.",
    )
    papers_retrieved: int = 0
    trials_retrieved: int = 0
    valid_drugs: list[str] = Field(default_factory=list)
    normalized_drugs: list[str] = Field(default_factory=list)
    rejected_drugs: list[RejectedDrug] = Field(default_factory=list)
    valid_drug_disease_relationships: int = 0
    rejected_relationships: list[RejectedRelationship] = Field(default_factory=list)
    candidate_count: int = 0
    evidence_gaps: list[str] = Field(default_factory=list)
    source_counts: dict[str, int] = Field(default_factory=dict)
    source_statuses: list[SourceAttempt] = Field(
        default_factory=list,
        description="One structured status per retrieval source for this "
        "run (see SourceAttempt) — lets a caller tell 'API succeeded with "
        "zero relevant results' apart from 'API failed/timed out/was "
        "rate-limited', which evidence_gaps' free-text strings alone "
        "cannot guarantee.",
    )
    used_local_fallback: bool = False
    local_fallback_reason: Optional[str] = Field(
        default=None,
        description="Set only when used_local_fallback is true. Explains "
        "*why* the cached local corpus was consulted — a live-source "
        "failure ('...were unavailable, using cached evidence as a "
        "secondary source') reads very differently from a clean empty "
        "search ('...found no case-relevant results; checked cached "
        "evidence for validated, relevant signals').",
    )
    llm_interpretation_status: Optional[str] = Field(
        default=None,
        description="Short status string for the optional Phase 4 LLM "
        "interpretation layer this run, e.g. 'disabled_no_api_key', "
        "'success (3 candidate(s) interpreted)', 'attempted_but_failed'. "
        "None only for analyses run before this field existed.",
    )


class AnalysisResult(BaseModel):
    case_id: int
    primary_condition: str
    analyzed_at: datetime
    candidates: list[CandidateOut]
    research_metadata: ResearchMetadata = Field(default_factory=ResearchMetadata)


class CandidateChange(BaseModel):
    """One candidate drug's change between a case's saved snapshot and a
    fresh re-analysis — the "new evidence detected" unit (Phase 3). Only
    candidates with an actual detected change are included; a drug whose
    evidence is identical to the snapshot never appears here."""

    drug: str
    is_new_candidate: bool = Field(
        description="True if this drug did not appear as a candidate at all "
        "in the saved snapshot."
    )
    evidence_tier_before: Optional[str] = Field(
        default=None, description="null when is_new_candidate is true."
    )
    evidence_tier_after: str
    evidence_score_before: Optional[float] = None
    evidence_score_after: float
    new_supporting_source_ids: list[str] = Field(
        default_factory=list,
        description="Real source_ids (trial/paper/label ids) present now but "
        "not in the snapshot.",
    )
    newly_conflicted_comorbidities: list[str] = Field(
        default_factory=list,
        description="Comorbidities that are 'conflict_detected' now but were "
        "not in the snapshot (i.e. a new safety/context flag appeared).",
    )
    summary: str = Field(
        description="Non-prescriptive, human-readable description of what "
        "changed, e.g. 'Evidence strength changed: MODERATE -> HIGH.'"
    )


class EvidenceCheckResult(BaseModel):
    """Result of comparing a saved case's snapshot against a fresh
    re-analysis (Phase 3's manually-triggered 'Re-check for new evidence').
    Always returned in full, even when nothing changed — has_new_evidence
    is the explicit signal, never an empty/omitted response."""

    case_id: int
    primary_condition: str
    snapshot_analyzed_at: Optional[datetime] = Field(
        description="When the compared-against snapshot was taken (case save "
        "time). null if this case has never been saved with an analysis."
    )
    checked_at: datetime
    has_new_evidence: bool
    changes: list[CandidateChange] = Field(default_factory=list)
    new_papers: list[str] = Field(default_factory=list)
    new_trials: list[str] = Field(default_factory=list)
    changed_evidence: list[str] = Field(default_factory=list)
    new_candidates: list[str] = Field(default_factory=list)
    removed_invalidated_candidates: list[str] = Field(default_factory=list)
    message: str


class CaseWithAnalysis(BaseModel):
    case: CaseOut
    last_analysis: Optional[AnalysisResult] = None
    last_evidence_check: Optional[EvidenceCheckResult] = None


class CaseConflictOut(BaseModel):
    """One source-backed safety/context flag for the dashboard's
    cross-case conflict list (GET /cases/conflicts) — every field here
    traces to a real ComorbidityCheck with status 'conflict_detected' on a
    saved case's last analysis, never inferred from two strings merely
    looking related."""

    case_id: int
    primary_condition: str
    drug: str
    comorbidity: str
    evidence_excerpt: Optional[str]
    source: str = Field(description="Where the conflict evidence came from, e.g. 'openfda'.")


class RecheckAllResult(BaseModel):
    """Response for the dashboard-level 'check all saved cases' action —
    still a manually-triggered batch action, not background monitoring."""

    checked_count: int
    cases_with_new_evidence_count: int
    results: list[EvidenceCheckResult]
