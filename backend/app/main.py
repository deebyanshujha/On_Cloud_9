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

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import desc, func as sa_func

from app.core.case_analysis import analyze_case
from app.core.auth import create_access_token, find_user, get_current_scholar, hash_password, profile_for, verify_password
from app.core.config import SEARCH_RESULT_LIMIT
from app.core.evidence_diff import diff_candidates
from app.core.runtime_research import run_runtime_case_research
from app.core.scoring import run_comparison
from app.core.search import rank_search_results
from app.core.terminology import search_conditions, search_medications
from app.ingestion.store import (
    create_case,
    find_matching_case,
    get_case,
    get_case_conditions,
    get_case_medications,
    list_cases,
    load_all_approved_indications,
    load_all_documents,
    load_case_analysis,
    load_case_research_evidence,
    load_case_snapshot,
    load_evidence_check,
    load_source_statuses,
    save_case_analysis,
    save_case_snapshot,
    save_evidence_check,
    set_case_saved,
)
from app.models.case import CaseRecord
from app.models.user import ScholarContributionRecord, UserRecord
from app.models.db import SessionLocal, init_db
from app.schemas.api import (
    SearchResultsOut,
    SignalOut,
    TerminologyEntry,
    TerminologySearchOut,
    build_signal_out,
)
from app.schemas.case import (
    AnalysisResult,
    CaseConflictOut,
    CaseCreate,
    CaseOut,
    CaseSummaryOut,
    CaseUpdate,
    CaseWithAnalysis,
    EvidenceCheckResult,
    RecheckAllResult,
)
from app.schemas.auth import (
    AuthSession, ScholarContributionCreate, ScholarContributionOut, ScholarCredentials,
    ScholarLogin, ScholarProfile, ScholarProfileUpdate,
)
from app.schemas.discussion import (
    LikeOut,
    ReplyCreate,
    ReplyOut,
    ThreadCreate,
    ThreadListOut,
    ThreadOut,
    ThreadSummaryOut,
)
from app.models.discussion import DiscussionLike, DiscussionReply, DiscussionThread


def _cache_source_ids(records) -> tuple[set[str], set[str]]:
    paper_ids: set[str] = set()
    trial_ids: set[str] = set()
    for record in records:
        if record.source == "clinicaltrials":
            trial_ids.add(record.source_id)
        else:
            paper_ids.add(f"{record.source}:{record.source_id}")
    return paper_ids, trial_ids


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


@app.post("/auth/register", response_model=AuthSession, status_code=status.HTTP_201_CREATED)
def register_scholar(credentials: ScholarCredentials) -> AuthSession:
    email = credentials.email.strip().lower()
    username = credentials.username.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Username may use letters, numbers, hyphens, and underscores")

    session = SessionLocal()
    try:
        if find_user(session, email) or find_user(session, username):
            raise HTTPException(status_code=409, detail="Email or username is already registered")
        user = UserRecord(email=email, username=username, password_hash=hash_password(credentials.password))
        session.add(user)
        session.commit()
        session.refresh(user)
        return AuthSession(access_token=create_access_token(user), profile=profile_for(user))
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email or username is already registered")
    finally:
        session.close()


@app.post("/auth/login", response_model=AuthSession)
def login_scholar(credentials: ScholarLogin) -> AuthSession:
    session = SessionLocal()
    try:
        user = find_user(session, credentials.identifier)
        if user is None or not verify_password(credentials.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email/username or password")
        return AuthSession(access_token=create_access_token(user), profile=profile_for(user))
    finally:
        session.close()


@app.get("/auth/me", response_model=ScholarProfile)
def scholar_profile(profile: ScholarProfile = Depends(get_current_scholar)) -> ScholarProfile:
    return profile


@app.patch("/auth/me", response_model=ScholarProfile)
def update_scholar_profile(
    update: ScholarProfileUpdate, profile: ScholarProfile = Depends(get_current_scholar)
) -> ScholarProfile:
    session = SessionLocal()
    try:
        user = session.get(UserRecord, profile.id)
        if user is None:
            raise HTTPException(status_code=404, detail="Scholar account not found")
        for field, value in update.model_dump().items():
            setattr(user, field, value.strip() if isinstance(value, str) else value)
        session.commit()
        session.refresh(user)
        return profile_for(user)
    finally:
        session.close()


def _contribution_out(record: ScholarContributionRecord, author: UserRecord) -> ScholarContributionOut:
    return ScholarContributionOut(
        id=record.id, title=record.title, summary=record.summary, drug=record.drug, disease=record.disease,
        source_url=record.source_url, author_name=author.full_name or author.username,
        organization=author.organization, created_at=record.created_at,
    )


@app.get("/community-research", response_model=list[ScholarContributionOut])
def community_research() -> list[ScholarContributionOut]:
    session = SessionLocal()
    try:
        rows = session.execute(
            select(ScholarContributionRecord, UserRecord)
            .join(UserRecord, UserRecord.id == ScholarContributionRecord.user_id)
            .order_by(ScholarContributionRecord.created_at.desc())
            .limit(30)
        ).all()
        return [_contribution_out(record, author) for record, author in rows]
    finally:
        session.close()


@app.post("/scholar/contributions", response_model=ScholarContributionOut, status_code=status.HTTP_201_CREATED)
def create_scholar_contribution(
    contribution: ScholarContributionCreate, profile: ScholarProfile = Depends(get_current_scholar)
) -> ScholarContributionOut:
    session = SessionLocal()
    try:
        record = ScholarContributionRecord(
            user_id=profile.id, **{key: value.strip() if isinstance(value, str) else value for key, value in contribution.model_dump().items()}
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        author = session.get(UserRecord, profile.id)
        return _contribution_out(record, author)
    finally:
        session.close()


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


@app.get("/search", response_model=SearchResultsOut)
def search(
    q: str,
    request: Request,
    limit: int = Query(default=SEARCH_RESULT_LIMIT, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchResultsOut:
    """Bounded, ranked search over the in-memory signal feed (2026-08-20 fix
    — see PROGRESS.md's data-imbalance/search-overwhelm audit). Ranking is
    match-quality-first (exact > starts-with > substring, see
    app/core/search.py), not insertion order; `limit`/`offset` bound how
    much of that ranked list actually comes back per request, default from
    config's SEARCH_RESULT_LIMIT — same env-var-driven pattern as the
    discovery scan-budget knobs."""
    query = q.strip().lower()
    if not query:
        return SearchResultsOut(results=[], total=0, limit=limit, offset=offset)

    ranked = rank_search_results(request.app.state.signals, query)
    page = ranked[offset : offset + limit]
    return SearchResultsOut(results=page, total=len(ranked), limit=limit, offset=offset)


@app.get("/medications/search", response_model=TerminologySearchOut)
def medications_search(q: str = Query(default="")) -> TerminologySearchOut:
    """Clean medication-name autocomplete for the New Case form — backed by
    NLM's RxTerms (see app.core.terminology), never raw ingested
    intervention names or openFDA label text."""
    results, unavailable = search_medications(q)
    return TerminologySearchOut(
        results=[TerminologyEntry(name=r.name) for r in results],
        source_unavailable=unavailable,
    )


@app.get("/conditions/search", response_model=TerminologySearchOut)
def conditions_search(q: str = Query(default="")) -> TerminologySearchOut:
    """Clean disease/condition-name autocomplete for the New Case form —
    backed by NLM's `conditions` table (see app.core.terminology), never raw
    trial titles or openFDA indications_and_usage paragraphs."""
    results, unavailable = search_conditions(q)
    return TerminologySearchOut(
        results=[TerminologyEntry(name=r.name) for r in results],
        source_unavailable=unavailable,
    )


# --- TheraLens: Cases -------------------------------------------------------
# Backend-only phase. Cases are analyzed against whatever documents/approved
# indications are already in arbitrage.db from the existing ingestion
# pipeline — no new ingestion logic here, same "read layer over the existing
# pipeline" pattern as /signals above.


def _load_analysis_result(analysis_record) -> AnalysisResult | None:
    """Stored analysis JSON predates a CandidateOut schema change (e.g. the
    2026-08-20 redesign's evidence_tier/evidence_tier_reason fields) and no
    longer validates — treat that the same as "never analyzed" rather than
    500ing the whole page, since the fix (re-analyze) is a normal user
    action already surfaced in the UI, not a data-loss situation."""
    if analysis_record is None:
        return None
    try:
        return AnalysisResult.model_validate_json(analysis_record.result_json)
    except ValidationError:
        return None


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

    result = _load_analysis_result(analysis_record)
    if result is not None:
        last_analyzed_at = analysis_record.analyzed_at
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
    """Duplicate-case guard (2026-08-20 redesign): submitting the exact same
    primary condition + comorbidity set + medication set twice reuses the
    existing case (200, same id) instead of creating a lookalike duplicate,
    unless the caller explicitly opts in with allow_duplicate=true. Returning
    200 with the pre-existing case (not a 409) keeps the New Case form's
    happy path a single call either way — "create or resume" reads as one
    action to the caller, not two different outcomes to branch on."""
    init_db()
    session = SessionLocal()
    try:
        if not payload.allow_duplicate:
            existing = find_matching_case(
                session,
                primary_condition=payload.primary_condition,
                comorbidities=payload.comorbidities,
                current_medications=payload.current_medications,
            )
            if existing is not None:
                return _case_out(session, existing)

        case = create_case(
            session,
            primary_condition=payload.primary_condition,
            comorbidities=payload.comorbidities,
            current_medications=payload.current_medications,
        )
        return _case_out(session, case)
    finally:
        session.close()


@app.get("/cases/conflicts", response_model=list[CaseConflictOut])
def list_case_conflicts() -> list[CaseConflictOut]:
    """Cross-case, source-backed safety/context flags for the dashboard —
    every 'conflict_detected' comorbidity check across every saved case's
    last analysis, read straight off the already-stored result JSON (no
    recomputation, same read-layer pattern as everything else here). Lets
    the dashboard show 'Drug X — potential conflict with Heart Failure — FDA
    label — [evidence excerpt]' instead of a bare per-case count."""
    init_db()
    session = SessionLocal()
    try:
        out: list[CaseConflictOut] = []
        for case in list_cases(session):
            if not case.saved:
                continue
            analysis_record = load_case_analysis(session, case.id)
            result = _load_analysis_result(analysis_record)
            if result is None:
                continue
            for candidate in result.candidates:
                for check in candidate.comorbidity_checks:
                    if check.status != "conflict_detected":
                        continue
                    out.append(
                        CaseConflictOut(
                            case_id=case.id,
                            primary_condition=case.primary_condition,
                            drug=candidate.drug,
                            comorbidity=check.comorbidity,
                            evidence_excerpt=check.evidence,
                            source="openfda",
                        )
                    )
        return out
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
        last_analysis = _load_analysis_result(analysis_record)
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
        local_documents = load_all_documents(session)
        approved = load_all_approved_indications(session)
        runtime = run_runtime_case_research(
            session,
            case_id=case.id,
            primary_condition=case.primary_condition,
            comorbidities=comorbidities,
            current_medications=get_case_medications(session, case_id),
            local_approved=approved,
            local_documents=local_documents,
        )
        documents = runtime.documents
        approved = runtime.approved_indications

        candidates = analyze_case(
            primary_condition=case.primary_condition,
            comorbidities=comorbidities,
            documents=documents,
            approved=approved,
            target_conditions=comorbidities,
        )
        runtime.metadata.candidate_count = len(candidates)

        result = AnalysisResult(
            case_id=case.id,
            primary_condition=case.primary_condition,
            analyzed_at=datetime.now(timezone.utc),
            candidates=candidates,
            research_metadata=runtime.metadata,
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
    snapshot = _load_analysis_result(snapshot_record)
    if snapshot is None:
        return None

    comorbidities = get_case_conditions(session, case.id)
    previous_papers, previous_trials = _cache_source_ids(
        load_case_research_evidence(session, case.id)
    )
    local_documents = load_all_documents(session)
    approved = load_all_approved_indications(session)
    runtime = run_runtime_case_research(
        session,
        case_id=case.id,
        primary_condition=case.primary_condition,
        comorbidities=comorbidities,
        current_medications=get_case_medications(session, case.id),
        local_approved=approved,
        local_documents=local_documents,
    )
    documents = runtime.documents
    approved = runtime.approved_indications
    candidates = analyze_case(
        primary_condition=case.primary_condition,
        comorbidities=comorbidities,
        documents=documents,
        approved=approved,
        target_conditions=comorbidities,
    )
    runtime.metadata.candidate_count = len(candidates)

    now = datetime.now(timezone.utc)
    # Re-checking also refreshes the "last analysis" record, same as
    # POST /analyze — the case page should reflect the freshest run either
    # way, not just whatever the diff was computed against.
    fresh_result = AnalysisResult(
        case_id=case.id,
        primary_condition=case.primary_condition,
        analyzed_at=now,
        candidates=candidates,
        research_metadata=runtime.metadata,
    )
    save_case_analysis(session, case.id, fresh_result.model_dump_json())

    changes = diff_candidates(snapshot.candidates, candidates)
    new_papers = sorted(runtime.paper_source_ids - previous_papers)
    new_trials = sorted(runtime.trial_source_ids - previous_trials)
    snapshot_drugs = {c.drug for c in snapshot.candidates}
    current_drugs = {c.drug for c in candidates}
    new_candidate_drugs = sorted(current_drugs - snapshot_drugs)
    removed_candidate_drugs = sorted(snapshot_drugs - current_drugs)
    has_new_evidence = bool(changes or new_papers or new_trials)
    if changes:
        message = f"New evidence detected for {len(changes)} candidate(s) since this case was saved."
    elif has_new_evidence:
        message = (
            f"New source evidence found since this case was saved "
            f"({len(new_papers)} publication(s), {len(new_trials)} trial(s))."
        )
    else:
        message = "No new evidence detected since this case was saved."

    result = EvidenceCheckResult(
        case_id=case.id,
        primary_condition=case.primary_condition,
        snapshot_analyzed_at=snapshot.analyzed_at,
        checked_at=now,
        has_new_evidence=has_new_evidence,
        changes=changes,
        new_papers=new_papers,
        new_trials=new_trials,
        changed_evidence=[change.summary for change in changes],
        new_candidates=new_candidate_drugs,
        removed_invalidated_candidates=removed_candidate_drugs,
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


# --- Research Discussion / Community Threads --------------------------------
# New feature: a researcher-focused discussion system that lives alongside
# the existing signal/drug/case pages. All data persists in the same
# arbitrage.db; patterns follow the existing read-layer endpoints above.


def _thread_summary(t: DiscussionThread) -> ThreadSummaryOut:
    return ThreadSummaryOut(
        id=t.id,
        title=t.title,
        category=t.category,
        author=t.author,
        pinned=t.pinned,
        drug_name=t.drug_name,
        disease_name=t.disease_name,
        signal_key=t.signal_key,
        reply_count=t.reply_count,
        like_count=t.like_count,
        created_at=t.created_at,
        last_activity_at=t.last_activity_at,
    )


def _reply_out(r: DiscussionReply) -> ReplyOut:
    return ReplyOut(
        id=r.id,
        thread_id=r.thread_id,
        body=r.body,
        author=r.author,
        like_count=r.like_count,
        created_at=r.created_at,
    )


@app.get("/discussions", response_model=ThreadListOut)
def list_discussions(
    q: str = Query(default=""),
    category: str = Query(default=""),
    drug: str = Query(default=""),
    disease: str = Query(default=""),
    signal_key: str = Query(default=""),
    sort: str = Query(default="newest"),  # newest | active | discussed
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ThreadListOut:
    """List discussion threads with optional search, category/context filters,
    sort order, and pagination. Pinned threads always surface first within
    each page."""
    init_db()
    session = SessionLocal()
    try:
        query_obj = session.query(DiscussionThread)

        if q.strip():
            like = f"%{q.strip().lower()}%"
            query_obj = query_obj.filter(
                DiscussionThread.title.ilike(like)
                | DiscussionThread.body.ilike(like)
                | DiscussionThread.author.ilike(like)
            )
        if category.strip():
            query_obj = query_obj.filter(DiscussionThread.category == category.strip())
        if drug.strip():
            query_obj = query_obj.filter(
                DiscussionThread.drug_name.ilike(f"%{drug.strip()}%")
            )
        if disease.strip():
            query_obj = query_obj.filter(
                DiscussionThread.disease_name.ilike(f"%{disease.strip()}%")
            )
        if signal_key.strip():
            query_obj = query_obj.filter(
                DiscussionThread.signal_key == signal_key.strip()
            )

        total = query_obj.count()

        if sort == "active":
            query_obj = query_obj.order_by(
                desc(DiscussionThread.pinned),
                desc(DiscussionThread.last_activity_at),
            )
        elif sort == "discussed":
            query_obj = query_obj.order_by(
                desc(DiscussionThread.pinned),
                desc(DiscussionThread.reply_count),
                desc(DiscussionThread.last_activity_at),
            )
        else:  # newest
            query_obj = query_obj.order_by(
                desc(DiscussionThread.pinned),
                desc(DiscussionThread.created_at),
            )

        threads = query_obj.offset(offset).limit(limit).all()
        return ThreadListOut(
            threads=[_thread_summary(t) for t in threads],
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        session.close()


@app.get("/discussions/by-context", response_model=ThreadListOut)
def discussions_by_context(
    drug: str = Query(default=""),
    disease: str = Query(default=""),
    signal_key: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
) -> ThreadListOut:
    """Return threads contextually linked to a specific drug, disease, or
    drug→disease signal — used by DrugExplorer and OpportunityCard to show
    relevant community discussions inline."""
    init_db()
    session = SessionLocal()
    try:
        query_obj = session.query(DiscussionThread)
        filters = []
        if signal_key.strip():
            filters.append(DiscussionThread.signal_key == signal_key.strip())
        if drug.strip():
            filters.append(DiscussionThread.drug_name.ilike(f"%{drug.strip()}%"))
        if disease.strip():
            filters.append(DiscussionThread.disease_name.ilike(f"%{disease.strip()}%"))

        if not filters:
            return ThreadListOut(threads=[], total=0, limit=limit, offset=0)

        from sqlalchemy import or_
        query_obj = query_obj.filter(or_(*filters))
        total = query_obj.count()
        threads = (
            query_obj
            .order_by(desc(DiscussionThread.last_activity_at))
            .limit(limit)
            .all()
        )
        return ThreadListOut(
            threads=[_thread_summary(t) for t in threads],
            total=total,
            limit=limit,
            offset=0,
        )
    finally:
        session.close()


@app.post("/discussions", response_model=ThreadOut)
def create_discussion(payload: ThreadCreate) -> ThreadOut:
    """Create a new discussion thread. Context fields (drug_name, disease_name,
    signal_key) are optional — set them when creating from drug/signal pages."""
    init_db()
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        thread = DiscussionThread(
            title=payload.title.strip(),
            category=payload.category,
            body=payload.body.strip(),
            author=payload.author.strip(),
            drug_name=payload.drug_name.strip() if payload.drug_name else None,
            disease_name=payload.disease_name.strip() if payload.disease_name else None,
            signal_key=payload.signal_key.strip() if payload.signal_key else None,
            reply_count=0,
            like_count=0,
            created_at=now,
            last_activity_at=now,
        )
        session.add(thread)
        session.commit()
        session.refresh(thread)
        return ThreadOut(
            **_thread_summary(thread).model_dump(),
            body=thread.body,
            replies=[],
        )
    finally:
        session.close()


@app.get("/discussions/{thread_id}", response_model=ThreadOut)
def get_discussion(thread_id: int) -> ThreadOut:
    """Fetch a thread with its full body text and all replies."""
    init_db()
    session = SessionLocal()
    try:
        thread = session.get(DiscussionThread, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        replies = (
            session.query(DiscussionReply)
            .filter(DiscussionReply.thread_id == thread_id)
            .order_by(DiscussionReply.created_at)
            .all()
        )
        return ThreadOut(
            **_thread_summary(thread).model_dump(),
            body=thread.body,
            replies=[_reply_out(r) for r in replies],
        )
    finally:
        session.close()


@app.post("/discussions/{thread_id}/replies", response_model=ReplyOut)
def post_reply(thread_id: int, payload: ReplyCreate) -> ReplyOut:
    """Add a reply to an existing discussion thread. Updates the thread's
    reply_count and last_activity_at denormalized fields."""
    init_db()
    session = SessionLocal()
    try:
        thread = session.get(DiscussionThread, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        now = datetime.now(timezone.utc)
        reply = DiscussionReply(
            thread_id=thread_id,
            body=payload.body.strip(),
            author=payload.author.strip(),
            like_count=0,
            created_at=now,
        )
        session.add(reply)
        thread.reply_count = (thread.reply_count or 0) + 1
        thread.last_activity_at = now
        session.commit()
        session.refresh(reply)
        return _reply_out(reply)
    finally:
        session.close()


@app.post("/discussions/{thread_id}/like", response_model=LikeOut)
def like_thread(thread_id: int, author: str = Query(min_length=1)) -> LikeOut:
    """Toggle a like on a discussion thread. Idempotent — calling twice for
    the same (thread, author) pair removes the like (unlike)."""
    init_db()
    session = SessionLocal()
    try:
        thread = session.get(DiscussionThread, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        existing = (
            session.query(DiscussionLike)
            .filter(
                DiscussionLike.target_type == "thread",
                DiscussionLike.target_id == thread_id,
                DiscussionLike.author == author,
            )
            .first()
        )
        if existing:
            session.delete(existing)
            thread.like_count = max(0, (thread.like_count or 1) - 1)
            liked = False
        else:
            session.add(
                DiscussionLike(
                    target_type="thread",
                    target_id=thread_id,
                    author=author,
                    created_at=datetime.now(timezone.utc),
                )
            )
            thread.like_count = (thread.like_count or 0) + 1
            liked = True
        session.commit()
        session.refresh(thread)
        return LikeOut(target_type="thread", target_id=thread_id, liked=liked, new_count=thread.like_count)
    finally:
        session.close()


@app.post("/discussions/replies/{reply_id}/like", response_model=LikeOut)
def like_reply(reply_id: int, author: str = Query(min_length=1)) -> LikeOut:
    """Toggle a like on a reply. Same toggle semantics as like_thread."""
    init_db()
    session = SessionLocal()
    try:
        reply = session.get(DiscussionReply, reply_id)
        if reply is None:
            raise HTTPException(status_code=404, detail=f"Reply {reply_id} not found")
        existing = (
            session.query(DiscussionLike)
            .filter(
                DiscussionLike.target_type == "reply",
                DiscussionLike.target_id == reply_id,
                DiscussionLike.author == author,
            )
            .first()
        )
        if existing:
            session.delete(existing)
            reply.like_count = max(0, (reply.like_count or 1) - 1)
            liked = False
        else:
            session.add(
                DiscussionLike(
                    target_type="reply",
                    target_id=reply_id,
                    author=author,
                    created_at=datetime.now(timezone.utc),
                )
            )
            reply.like_count = (reply.like_count or 0) + 1
            liked = True
        session.commit()
        session.refresh(reply)
        return LikeOut(target_type="reply", target_id=reply_id, liked=liked, new_count=reply.like_count)
    finally:
        session.close()
