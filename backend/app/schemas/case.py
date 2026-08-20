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


class CaseCreate(BaseModel):
    primary_condition: str
    comorbidities: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
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


class CandidateOut(BaseModel):
    """One repurposing candidate surfaced for this case's primary condition,
    as a research signal — never a recommendation."""

    drug: str
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


class AnalysisResult(BaseModel):
    case_id: int
    primary_condition: str
    analyzed_at: datetime
    candidates: list[CandidateOut]


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
