"""FastAPI backend (Step 8). Serves the signals already produced by Steps
3-6's ingestion + Step 5's comparison/scoring engine — no new
ingestion/comparison logic lives here, this is purely a read API over
what's already in `arbitrage.db`.

Signals are computed once at startup (there's no live re-polling yet —
that's the deferred Step 7) and held in memory, since recomputing a
~350-signal comparison per request would be pointless work for data that
doesn't change without re-running the ingestion scripts.

Run from backend/: uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.case_analysis import analyze_case
from app.core.evidence_diff import diff_candidates
from app.core.scoring import run_comparison
from app.ingestion.store import (
    create_case,
    get_case,
    get_case_conditions,
    get_case_medications,
    list_cases,
    load_all_approved_indications,
    load_all_documents,
    load_case_analysis,
    load_case_snapshot,
    load_evidence_check,
    load_source_statuses,
    save_case_analysis,
    save_case_snapshot,
    save_evidence_check,
    set_case_saved,
)
from app.models.case import CaseRecord
from app.models.db import SessionLocal, init_db
from app.schemas.api import SignalOut, build_signal_out
from app.schemas.case import (
    AnalysisResult,
    CaseCreate,
    CaseOut,
    CaseSummaryOut,
    CaseUpdate,
    CaseWithAnalysis,
    EvidenceCheckResult,
    RecheckAllResult,
)


def _compute_signals() -> list[SignalOut]:
    init_db()
    session = SessionLocal()
    try:
        documents = load_all_documents(session)
        approved = load_all_approved_indications(session)
        statuses = load_source_statuses(session)
    finally:
        session.close()

    signals = run_comparison(documents, approved)
    source_status = {
        s.source: {
            "status": s.status,
            "message": s.message,
            "items_ingested": s.items_ingested,
            "checked_at": s.checked_at.isoformat() if s.checked_at else None,
        }
        for s in statuses
    }
    return [build_signal_out(s) for s in signals], source_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.signals, app.state.source_status = _compute_signals()
    yield


app = FastAPI(title="Biotech Arbitrage Engine API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status(request: Request) -> dict:
    """Per-source ingestion status from the most recent discovery run — a
    source that errored shows up here as "error" with a message instead of
    silently looking like it just found nothing (Step 10 fallback
    behavior)."""
    return {
        "signal_count": len(request.app.state.signals),
        "sources": request.app.state.source_status,
    }


@app.get("/signals", response_model=list[SignalOut])
def list_signals(request: Request) -> list[SignalOut]:
    return request.app.state.signals


@app.get("/signals/{drug}", response_model=list[SignalOut])
def signals_for_drug(drug: str, request: Request) -> list[SignalOut]:
    normalized = drug.strip().lower()
    matches = [s for s in request.app.state.signals if s.drug == normalized]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No signals found for drug '{drug}'")
    return matches


@app.get("/search", response_model=list[SignalOut])
def search(q: str, request: Request) -> list[SignalOut]:
    query = q.strip().lower()
    if not query:
        return []
    return [
        s
        for s in request.app.state.signals
        if query in s.drug or query in s.disease
    ]


# --- TheraLens: Cases -------------------------------------------------------
# Backend-only phase. Cases are analyzed against whatever documents/approved
# indications are already in arbitrage.db from the existing ingestion
# pipeline — no new ingestion logic here, same "read layer over the existing
# pipeline" pattern as /signals above.


def _case_out(session, case) -> CaseOut:
    return CaseOut(
        id=case.id,
        primary_condition=case.primary_condition,
        comorbidities=get_case_conditions(session, case.id),
        current_medications=get_case_medications(session, case.id),
        saved=case.saved,
        created_at=case.created_at,
    )


def _case_summary(case, analysis_record, evidence_check_record=None) -> CaseSummaryOut:
    candidate_count = conflict_count = None
    top_score: float | None = None
    last_analyzed_at = None

    if analysis_record is not None:
        last_analyzed_at = analysis_record.analyzed_at
        result = AnalysisResult.model_validate_json(analysis_record.result_json)
        candidate_count = len(result.candidates)
        conflict_count = sum(
            1
            for c in result.candidates
            if any(ck.status == "conflict_detected" for ck in c.comorbidity_checks)
        )
        top_score = max((c.research_priority_score for c in result.candidates), default=None)

    return CaseSummaryOut(
        id=case.id,
        primary_condition=case.primary_condition,
        comorbidities=[],
        current_medications=[],
        saved=case.saved,
        created_at=case.created_at,
        last_analyzed_at=last_analyzed_at,
        candidate_count=candidate_count,
        conflict_count=conflict_count,
        top_research_priority_score=top_score,
        has_new_evidence=evidence_check_record.has_new_evidence if evidence_check_record else None,
        evidence_checked_at=evidence_check_record.checked_at if evidence_check_record else None,
    )


@app.get("/cases", response_model=list[CaseSummaryOut])
def list_cases_endpoint() -> list[CaseSummaryOut]:
    init_db()
    session = SessionLocal()
    try:
        cases = list_cases(session)
        summaries = []
        for case in cases:
            conditions = get_case_conditions(session, case.id)
            medications = get_case_medications(session, case.id)
            analysis_record = load_case_analysis(session, case.id)
            evidence_check_record = load_evidence_check(session, case.id)
            summary = _case_summary(case, analysis_record, evidence_check_record)
            summary.comorbidities = conditions
            summary.current_medications = medications
            summaries.append(summary)
        return summaries
    finally:
        session.close()


@app.post("/cases", response_model=CaseOut)
def create_case_endpoint(payload: CaseCreate) -> CaseOut:
    init_db()
    session = SessionLocal()
    try:
        case = create_case(
            session,
            primary_condition=payload.primary_condition,
            comorbidities=payload.comorbidities,
            current_medications=payload.current_medications,
        )
        return _case_out(session, case)
    finally:
        session.close()


@app.get("/cases/{case_id}", response_model=CaseWithAnalysis)
def get_case_endpoint(case_id: int) -> CaseWithAnalysis:
    init_db()
    session = SessionLocal()
    try:
        case = get_case(session, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"No case found with id {case_id}")

        analysis_record = load_case_analysis(session, case_id)
        last_analysis = (
            AnalysisResult.model_validate_json(analysis_record.result_json)
            if analysis_record is not None
            else None
        )
        evidence_check_record = load_evidence_check(session, case_id)
        last_evidence_check = (
            EvidenceCheckResult.model_validate_json(evidence_check_record.result_json)
            if evidence_check_record is not None
            else None
        )
        return CaseWithAnalysis(
            case=_case_out(session, case),
            last_analysis=last_analysis,
            last_evidence_check=last_evidence_check,
        )
    finally:
        session.close()


@app.patch("/cases/{case_id}", response_model=CaseOut)
def update_case_endpoint(case_id: int, payload: CaseUpdate) -> CaseOut:
    """Phase 3: saving a case (saved=true) snapshots its current 'last
    analysis' (if one exists) as the baseline that 'Re-check for new
    evidence' will later diff against — see app/models/case.py's
    CaseSnapshotRecord docstring for why this is a separate, fixed
    snapshot rather than reusing the last-analysis record, which keeps
    getting overwritten."""
    init_db()
    session = SessionLocal()
    try:
        case = set_case_saved(session, case_id, payload.saved)
        if case is None:
            raise HTTPException(status_code=404, detail=f"No case found with id {case_id}")
        if payload.saved:
            analysis_record = load_case_analysis(session, case_id)
            if analysis_record is not None:
                save_case_snapshot(session, case_id, analysis_record.result_json)
        return _case_out(session, case)
    finally:
        session.close()


@app.post("/cases/{case_id}/analyze", response_model=AnalysisResult)
def analyze_case_endpoint(case_id: int) -> AnalysisResult:
    init_db()
    session = SessionLocal()
    try:
        case = get_case(session, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"No case found with id {case_id}")

        comorbidities = get_case_conditions(session, case_id)
        documents = load_all_documents(session)
        approved = load_all_approved_indications(session)

        candidates = analyze_case(
            primary_condition=case.primary_condition,
            comorbidities=comorbidities,
            documents=documents,
            approved=approved,
        )

        result = AnalysisResult(
            case_id=case.id,
            primary_condition=case.primary_condition,
            analyzed_at=datetime.now(timezone.utc),
            candidates=candidates,
        )
        save_case_analysis(session, case_id, result.model_dump_json())
        return result
    finally:
        session.close()


# --- TheraLens: Phase 3 — manually-triggered "new evidence" re-check -------
# Deliberately NOT continuous background monitoring (Step 7's scheduler
# stays deferred — see PROGRESS.md). A saved case's analysis is snapshotted
# at save time (see update_case_endpoint above); these endpoints re-run the
# same Phase 1 analysis engine against whatever's currently in arbitrage.db
# and diff the result against that snapshot.


def _run_recheck(session, case: CaseRecord) -> EvidenceCheckResult | None:
    """Returns None if this case has never been saved with an analysis
    snapshot to compare against (nothing to re-check yet)."""
    snapshot_record = load_case_snapshot(session, case.id)
    if snapshot_record is None:
        return None
    snapshot = AnalysisResult.model_validate_json(snapshot_record.result_json)

    comorbidities = get_case_conditions(session, case.id)
    documents = load_all_documents(session)
    approved = load_all_approved_indications(session)
    candidates = analyze_case(
        primary_condition=case.primary_condition,
        comorbidities=comorbidities,
        documents=documents,
        approved=approved,
    )

    now = datetime.now(timezone.utc)
    # Re-checking also refreshes the "last analysis" record, same as
    # POST /analyze — the case page should reflect the freshest run either
    # way, not just whatever the diff was computed against.
    fresh_result = AnalysisResult(
        case_id=case.id, primary_condition=case.primary_condition, analyzed_at=now, candidates=candidates
    )
    save_case_analysis(session, case.id, fresh_result.model_dump_json())

    changes = diff_candidates(snapshot.candidates, candidates)
    has_new_evidence = bool(changes)
    message = (
        f"New evidence detected for {len(changes)} candidate(s) since this case was saved."
        if has_new_evidence
        else "No new evidence detected since this case was saved."
    )

    result = EvidenceCheckResult(
        case_id=case.id,
        primary_condition=case.primary_condition,
        snapshot_analyzed_at=snapshot.analyzed_at,
        checked_at=now,
        has_new_evidence=has_new_evidence,
        changes=changes,
        message=message,
    )
    save_evidence_check(session, case.id, has_new_evidence, result.model_dump_json())
    return result


@app.post("/cases/{case_id}/recheck", response_model=EvidenceCheckResult)
def recheck_case_endpoint(case_id: int) -> EvidenceCheckResult:
    init_db()
    session = SessionLocal()
    try:
        case = get_case(session, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"No case found with id {case_id}")
        if not case.saved:
            raise HTTPException(
                status_code=400,
                detail="Case must be saved (with an existing analysis) before checking for new evidence.",
            )
        result = _run_recheck(session, case)
        if result is None:
            raise HTTPException(
                status_code=400,
                detail="No saved snapshot exists for this case — analyze and save it first.",
            )
        return result
    finally:
        session.close()


@app.post("/cases/recheck-all", response_model=RecheckAllResult)
def recheck_all_cases_endpoint() -> RecheckAllResult:
    """Dashboard-level 'check all saved cases' — still one explicit user
    action, run once over every saved case, not a scheduled job."""
    init_db()
    session = SessionLocal()
    try:
        results = [
            r
            for case in list_cases(session)
            if case.saved and (r := _run_recheck(session, case)) is not None
        ]
        return RecheckAllResult(
            checked_count=len(results),
            cases_with_new_evidence_count=sum(1 for r in results if r.has_new_evidence),
            results=results,
        )
    finally:
        session.close()
