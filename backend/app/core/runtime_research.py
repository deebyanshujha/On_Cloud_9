"""Case-specific runtime research.

This module is intentionally separate from global discovery. A case run
generates its own queries, retrieves papers/trials live, validates drug
entities, extracts only evidence-bearing therapeutic relationships, and
caches the retrieved evidence against the case.
"""
from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

import httpx
from sqlalchemy.orm import Session

from app.core.config import (
    CASE_RESEARCH_MAX_PAPERS,
    CASE_RESEARCH_MAX_RETRIES,
    CASE_RESEARCH_MAX_TRIALS,
    CASE_RESEARCH_RESULTS_PER_QUERY,
    CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
    CASE_RESEARCH_TIME_WINDOW_DAYS,
)
from app.core.disease_matching import STAGING_QUALIFIERS, diseases_match, is_junk_condition
from app.core.drug_normalization import (
    DRUG_CLASS_ALLOWLIST,
    is_junk_drug_name,
    is_valid_medication_entity,
    normalize_drug_name,
    resolve_rxnorm_id,
)
from app.core.http_fetch import get_with_retry
from app.core.scoring import build_approved_index, is_already_approved, normalize
from app.ingestion import openfda, pubmed as pubmed_ingestion
from app.ingestion.biorxiv import parse_publication_date, strip_html
from app.ingestion.clinicaltrials import CTGOV_STUDIES_URL, normalize_phase, parse_ctgov_date
from app.ingestion.store import save_case_research_evidence, upsert_approved_indications
from app.schemas.case import RejectedDrug, RejectedRelationship, ResearchMetadata, SourceAttempt
from app.schemas.document import ApprovedIndication, Document, EvidenceType

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_THERAPEUTIC_RE = re.compile(
    r"\b("
    r"investigat(?:e|ed|es|ing)?|evaluat(?:e|ed|es|ing)?|stud(?:y|ied|ies|ying)|"
    r"trial|randomi[sz]ed|intervention|administer(?:ed|ing)?|treated|treatment|"
    r"therapy|therapeutic|efficacy|effect(?:s)?|outcome(?:s)?|improv(?:e|ed|es|ing)?|"
    r"reduc(?:e|ed|es|ing)?|lower(?:ed|ing)?|benefit(?:ed|s)?|for the treatment"
    r")\b",
    re.IGNORECASE,
)
_MENTION_ONLY = "MENTION_ONLY"
_MAX_REJECTED_RELATIONSHIPS = 200


@dataclass
class SourceEvidenceRecord:
    query: str
    source: str
    source_id: str
    url: str | None
    title: str | None
    date: date | None
    normalized_drugs: list[str]
    normalized_diseases: list[str]
    relationships: list[dict]


@dataclass
class RuntimeResearchResult:
    documents: list[Document]
    approved_indications: list[ApprovedIndication]
    metadata: ResearchMetadata
    records: list[SourceEvidenceRecord] = field(default_factory=list)
    paper_source_ids: set[str] = field(default_factory=set)
    trial_source_ids: set[str] = field(default_factory=set)


def generate_case_queries(
    primary_condition: str,
    comorbidities: list[str],
    current_medications: list[str],
) -> list[str]:
    """Build multiple case-specific research queries from the user's case."""
    queries: dict[str, None] = {}

    def add(query: str) -> None:
        cleaned = " ".join(query.split())
        if cleaned:
            queries.setdefault(cleaned, None)

    primary = primary_condition.strip()
    meds = [m.strip() for m in current_medications if m.strip()]
    comorbs = [c.strip() for c in comorbidities if c.strip()]

    add(f'"{primary}" drug repurposing')
    add(f'"{primary}" clinical trial')
    add(f'"{primary}" alternative indication')

    for comorbidity in comorbs:
        add(f'"{primary}" "{comorbidity}"')
        add(f'"{comorbidity}" "{primary}" drug')
        add(f'"{comorbidity}" drug treatment')
        add(f'"{comorbidity}" clinical trial')

    for medication in meds:
        add(f'"{medication}" "{primary}"')
        add(f'"{medication}" alternative indication')
        add(f'"{medication}" therapeutic effect "{primary}"')
        for comorbidity in comorbs:
            add(f'"{medication}" "{comorbidity}"')
            add(f'"{medication}" therapeutic effect "{comorbidity}"')

    return list(queries)


_PAREN_RE = re.compile(r"\([^)]*\)")


def _broaden_term(term: str) -> str:
    """Strip parenthetical qualifiers/ontology annotations and staging
    words so a verbose clinical-terminology label — e.g. "Diabetes - Type
    2 (adult, non-insulin-independent)", the kind of string an ICD/SNOMED-
    backed autocomplete can hand back — still has a searchable broad form
    once its exact phrase has proven to return nothing. Real, confirmed
    bug: that exact label, quoted verbatim (generate_case_queries' tier-1
    style), returns 0 hits from both Europe PMC and ClinicalTrials.gov
    (hitCount: 0, checked live) even though "diabetes"/"type 2 diabetes"
    have abundant real literature — the disease *concept* wasn't missing
    evidence, the exact-phrase query was too restrictive to find it."""
    text = _PAREN_RE.sub(" ", term)
    if " - " in text:
        text = text.split(" - ")[0]
    tokens = [t for t in _WORD_RE.findall(text.lower()) if t not in STAGING_QUALIFIERS]
    if not tokens:
        tokens = [t for t in _WORD_RE.findall(term.lower())]
    return " ".join(tokens)


def generate_broad_case_queries(
    primary_condition: str,
    comorbidities: list[str],
    current_medications: list[str],
) -> list[str]:
    """Second-tier, unquoted/broadened queries — deliberately not run by
    default. `run_runtime_case_research` only fires these when every
    tier-1 (`generate_case_queries`) query came back with zero raw items
    from every live source; see that function's "broadening" section for
    why raw-item-count (not post-relevance-filter document count) is the
    trigger. Fewer, broader terms than tier-1 on purpose — this is a
    bounded single retry, not a second full query fan-out."""
    queries: dict[str, None] = {}

    def add(query: str) -> None:
        cleaned = " ".join(query.split())
        if cleaned:
            queries.setdefault(cleaned, None)

    primary = _broaden_term(primary_condition)
    meds = [_broaden_term(m) for m in current_medications if m.strip()]
    comorbs = [_broaden_term(c) for c in comorbidities if c.strip()]

    if primary:
        add(f"{primary} drug treatment")

    for comorbidity in comorbs:
        if primary and comorbidity:
            add(f"{primary} {comorbidity}")

    for medication in meds:
        if not medication:
            continue
        if primary:
            add(f"{medication} {primary}")
        for comorbidity in comorbs:
            if comorbidity:
                add(f"{medication} {comorbidity}")

    return list(queries)


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _term_in_text(term: str, text: str) -> bool:
    term_tokens = _tokens(term)
    if not term_tokens:
        return False
    return term_tokens.issubset(_tokens(text))


def _condition_in_text(condition: str, text: str) -> bool:
    return diseases_match(condition, text)


def _target_conditions(primary_condition: str, comorbidities: list[str]) -> list[str]:
    targets: list[str] = []
    for raw in [primary_condition] + comorbidities:
        cleaned = normalize(raw)
        if cleaned and cleaned not in targets:
            targets.append(cleaned)
    return targets


def _matching_targets(text_or_condition: str, targets: list[str]) -> list[str]:
    return [target for target in targets if _condition_in_text(target, text_or_condition)]


def _is_therapeutic_relationship(text: str, drug: str, disease: str) -> bool:
    """Require therapeutic/investigational language near the drug+disease.

    A paper where both names appear somewhere in the abstract but never in
    a sentence/title with a therapeutic trigger is classified as
    MENTION_ONLY by the caller.
    """
    fragments = [text]
    fragments.extend(_SENTENCE_SPLIT_RE.split(text))
    for fragment in fragments:
        if not _term_in_text(drug, fragment):
            continue
        if not _condition_in_text(disease, fragment):
            continue
        if _THERAPEUTIC_RE.search(fragment):
            return True
    return False


def _publication_source_and_id(paper: dict) -> tuple[str, str] | None:
    pmid = paper.get("pmid")
    doi = paper.get("doi")
    source = (paper.get("source") or "").upper()
    if pmid:
        return ("pubmed" if source == "MED" else "europepmc", pmid)
    if doi:
        return ("europepmc", doi)
    source_id = paper.get("id")
    if source_id:
        return ("europepmc", source_id)
    return None


def _publication_url(source: str, source_id: str, paper: dict) -> str | None:
    if source == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{source_id}/"
    doi = paper.get("doi")
    if doi:
        return f"https://doi.org/{doi}"
    return f"https://europepmc.org/article/{paper.get('source', 'EXT')}/{source_id}"


def _classify_publication_evidence(paper: dict, text: str) -> EvidenceType:
    lower = text.lower()
    pub_types_raw = paper.get("pubTypeList", {}).get("pubType") or []
    pub_types = " ".join(pub_types_raw).lower() if isinstance(pub_types_raw, list) else str(pub_types_raw).lower()
    joined = f"{pub_types} {lower}"

    if "meta-analysis" in joined or "meta analysis" in joined:
        return "META_ANALYSIS"
    if "systematic review" in joined:
        return "SYSTEMATIC_REVIEW"
    if "randomized" in joined or "randomised" in joined:
        return "RANDOMIZED_TRIAL"
    if "case report" in joined:
        return "CASE_REPORT"
    if any(term in joined for term in ("cohort", "observational", "registry", "real-world", "real world")):
        return "OBSERVATIONAL"
    if any(term in joined for term in ("mouse", "mice", "murine", "rat ", "rats", "in vitro", "cell line")):
        return "PRECLINICAL"
    if any(term in joined for term in ("mechanism", "pathway", "biomarker", "signaling", "signalling")):
        return "MECHANISTIC"
    return "HUMAN_STUDY"


def _classify_trial_evidence(study: dict) -> EvidenceType:
    design = study.get("protocolSection", {}).get("designModule", {})
    allocation = ((design.get("designInfo") or {}).get("allocation") or "").lower()
    if "random" in allocation:
        return "RANDOMIZED_TRIAL"
    return "CLINICAL_TRIAL"


@dataclass
class QueryOutcome:
    """Result of fetching one query against one source — the unit
    everything else in this module (broadening decisions, source-status
    aggregation, evidence_gaps messages) is built from. `status` uses the
    same vocabulary as `SourceAttempt` (see app/schemas/case.py) minus
    "no_results"/"not_attempted": whether a query's `success` outcome
    found 0 or N items is a property of the *aggregate* across all queries
    for a source, not of one query in isolation (a query search that
    genuinely finds nothing is still a successful search)."""

    query: str
    status: str  # "success" | "timeout" | "http_error" | "parse_error" | "rate_limited"
    items: list[dict] = field(default_factory=list)
    error: str | None = None


def _fetch_europepmc_papers(query: str, *, since: date) -> QueryOutcome:
    """Materializes one query's Europe PMC results (paginated, retried on
    transient failures). A partial result set (some pages fetched
    successfully before a later page failed) is still returned as
    `"success"` with whatever was gathered — losing already-fetched real
    results to a later page's transient hiccup would be strictly worse
    than reporting what we have."""
    source_query = (
        f'({query}) AND HAS_ABSTRACT:Y '
        f"AND FIRST_PDATE:[{since.isoformat()} TO {date.today().isoformat()}]"
    )
    params = {
        "query": source_query,
        "format": "json",
        "resultType": "core",
        "pageSize": CASE_RESEARCH_RESULTS_PER_QUERY,
        "cursorMark": "*",
    }
    items: list[dict] = []
    with httpx.Client(timeout=30.0) as client:
        while True:
            outcome = get_with_retry(
                client, EUROPEPMC_SEARCH_URL, params,
                max_retries=CASE_RESEARCH_MAX_RETRIES, backoff_seconds=CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
            )
            if outcome.status != "success":
                if items:
                    return QueryOutcome(query=query, status="success", items=items)
                return QueryOutcome(query=query, status=outcome.status, error=outcome.error)
            try:
                payload = outcome.response.json()
            except ValueError as exc:
                if items:
                    return QueryOutcome(query=query, status="success", items=items)
                return QueryOutcome(query=query, status="parse_error", error=f"malformed Europe PMC JSON: {exc}")
            results = payload.get("resultList", {}).get("result", [])
            items.extend(results)
            if len(items) >= CASE_RESEARCH_RESULTS_PER_QUERY:
                return QueryOutcome(query=query, status="success", items=items[:CASE_RESEARCH_RESULTS_PER_QUERY])
            next_cursor = payload.get("nextCursorMark")
            if not results or not next_cursor or next_cursor == params["cursorMark"]:
                return QueryOutcome(query=query, status="success", items=items)
            params["cursorMark"] = next_cursor


def _fetch_ctgov_studies(query: str) -> QueryOutcome:
    params = {"query.term": query, "pageSize": CASE_RESEARCH_RESULTS_PER_QUERY}
    items: list[dict] = []
    with httpx.Client(timeout=30.0) as client:
        while True:
            outcome = get_with_retry(
                client, CTGOV_STUDIES_URL, params,
                max_retries=CASE_RESEARCH_MAX_RETRIES, backoff_seconds=CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
            )
            if outcome.status != "success":
                if items:
                    return QueryOutcome(query=query, status="success", items=items)
                return QueryOutcome(query=query, status=outcome.status, error=outcome.error)
            try:
                payload = outcome.response.json()
            except ValueError as exc:
                if items:
                    return QueryOutcome(query=query, status="success", items=items)
                return QueryOutcome(query=query, status="parse_error", error=f"malformed ClinicalTrials.gov JSON: {exc}")
            studies = payload.get("studies", [])
            items.extend(studies)
            if len(items) >= CASE_RESEARCH_RESULTS_PER_QUERY:
                return QueryOutcome(query=query, status="success", items=items[:CASE_RESEARCH_RESULTS_PER_QUERY])
            next_token = payload.get("nextPageToken")
            if not next_token:
                return QueryOutcome(query=query, status="success", items=items)
            params["pageToken"] = next_token


CASE_RESEARCH_FETCH_WORKERS = 8


def _fetch_papers_for_query_safe(query: str, since: date) -> QueryOutcome:
    """Network-only worker: materializes one query's papers so fetching
    across queries can run concurrently (the sequential per-query version
    of this loop was the dominant cost of a case run — ~2 dozen sequential
    HTTP round trips). Parsing/validation stays single-threaded afterward
    since it touches shared dedup state. Never raises: `_fetch_europepmc_
    papers` classifies every failure into `QueryOutcome.status` itself."""
    return _fetch_europepmc_papers(query, since=since)


def _fetch_pubmed_for_query_safe(query: str, since: date) -> QueryOutcome:
    papers, outcome = pubmed_ingestion.search_pubmed(
        query, since=since, page_size=CASE_RESEARCH_RESULTS_PER_QUERY, max_results=CASE_RESEARCH_RESULTS_PER_QUERY
    )
    if outcome.status != "success" and not papers:
        return QueryOutcome(query=query, status=outcome.status, error=outcome.error)
    return QueryOutcome(query=query, status="success", items=papers)


def _fetch_trials_for_query_safe(query: str) -> QueryOutcome:
    return _fetch_ctgov_studies(query)


def _validate_drug(
    raw_name: str,
    *,
    source: str,
    rejected: dict[tuple[str, str, str | None], RejectedDrug],
    resolver_cache: dict[str, str | None],
) -> str | None:
    if is_junk_drug_name(raw_name):
        rejected.setdefault(
            (raw_name, "rejected as non-drug intervention text", source),
            RejectedDrug(raw_name=raw_name, normalized_name=None, reason="rejected as non-drug intervention text", source=source),
        )
        return None

    canonical = normalize_drug_name(raw_name)
    if not canonical:
        rejected.setdefault(
            (raw_name, "empty after normalization", source),
            RejectedDrug(raw_name=raw_name, normalized_name=None, reason="empty after normalization", source=source),
        )
        return None

    # Salt/form stripping can turn a junk name that survived the raw-name
    # check into bare junk text (e.g. "Placebo Injection" -> "placebo",
    # which is itself an RxNorm concept and would otherwise pass the
    # resolver below) — re-check the *canonical* form too, not just raw.
    if is_junk_drug_name(canonical):
        rejected.setdefault(
            (raw_name, "rejected as non-drug intervention text", source),
            RejectedDrug(raw_name=raw_name, normalized_name=canonical, reason="rejected as non-drug intervention text", source=source),
        )
        return None

    if canonical in DRUG_CLASS_ALLOWLIST:
        return canonical

    if canonical not in resolver_cache:
        resolver_cache[canonical] = resolve_rxnorm_id(canonical)

    if resolver_cache[canonical]:
        return canonical

    rejected.setdefault(
        (raw_name, "no confident RxNorm resolution", source),
        RejectedDrug(raw_name=raw_name, normalized_name=canonical, reason="no confident RxNorm resolution", source=source),
    )
    return None


def _case_medication_drugs(
    current_medications: list[str],
    *,
    rejected: dict[tuple[str, str, str | None], RejectedDrug],
    resolver_cache: dict[str, str | None],
) -> list[str]:
    valid: dict[str, None] = {}
    for raw in current_medications:
        canonical = _validate_drug(
            raw, source="case_current_medication", rejected=rejected, resolver_cache=resolver_cache
        )
        if canonical:
            valid.setdefault(canonical, None)
    return list(valid)


def _add_rejected_relationship(
    metadata: ResearchMetadata,
    *,
    drug: str | None,
    disease: str | None,
    source: str,
    source_id: str,
    evidence_type: str,
    reason: str,
) -> None:
    if len(metadata.rejected_relationships) >= _MAX_REJECTED_RELATIONSHIPS:
        return
    item = RejectedRelationship(
        drug=drug,
        disease=disease,
        source=source,
        source_id=source_id,
        evidence_type=evidence_type,
        reason=reason,
    )
    key = item.model_dump_json()
    existing = {r.model_dump_json() for r in metadata.rejected_relationships}
    if key not in existing:
        metadata.rejected_relationships.append(item)


def _parse_paper(
    paper: dict,
    *,
    query: str,
    targets: list[str],
    case_drugs: list[str],
    metadata: ResearchMetadata,
) -> tuple[list[Document], SourceEvidenceRecord | None]:
    source_and_id = _publication_source_and_id(paper)
    if source_and_id is None:
        return [], None
    source, source_id = source_and_id

    title = paper.get("title") or ""
    abstract = strip_html(paper.get("abstractText") or "")
    text = f"{title}. {abstract}".strip()
    if not text:
        return [], None

    matching_diseases = _matching_targets(text, targets)
    if not matching_diseases:
        return [], None

    drugs = [drug for drug in case_drugs if _term_in_text(drug, text)]
    relationships: list[dict] = []
    documents: list[Document] = []
    evidence_type = _classify_publication_evidence(paper, text)
    publication_date = parse_publication_date(paper.get("firstPublicationDate"))
    url = _publication_url(source, source_id, paper)

    for drug in drugs:
        for disease in matching_diseases:
            if _is_therapeutic_relationship(text, drug, disease):
                relationships.append(
                    {
                        "drug": drug,
                        "disease": disease,
                        "evidence_type": evidence_type,
                        "status": "EVIDENCE",
                        "reason": "therapeutic or investigational language found near drug and disease",
                    }
                )
                documents.append(
                    Document(
                        drug=drug,
                        disease=disease,
                        source=source,
                        source_id=source_id,
                        phase=None,
                        date=publication_date,
                        url=url,
                        num_mentions=1,
                        evidence_type=evidence_type,
                    )
                )
            else:
                relationships.append(
                    {
                        "drug": drug,
                        "disease": disease,
                        "evidence_type": _MENTION_ONLY,
                        "status": _MENTION_ONLY,
                        "reason": "drug and disease co-occurred without therapeutic/investigational evidence",
                    }
                )
                _add_rejected_relationship(
                    metadata,
                    drug=drug,
                    disease=disease,
                    source=source,
                    source_id=source_id,
                    evidence_type=_MENTION_ONLY,
                    reason="mention-only co-occurrence",
                )

    if not relationships:
        return [], None

    record = SourceEvidenceRecord(
        query=query,
        source=source,
        source_id=source_id,
        url=url,
        title=title,
        date=publication_date,
        normalized_drugs=drugs,
        normalized_diseases=matching_diseases,
        relationships=relationships,
    )
    return documents, record


def _study_title(study: dict) -> str | None:
    return (
        study.get("protocolSection", {})
        .get("identificationModule", {})
        .get("briefTitle")
    )


def _parse_trial(
    study: dict,
    *,
    query: str,
    targets: list[str],
    metadata: ResearchMetadata,
    rejected_drugs: dict[tuple[str, str, str | None], RejectedDrug],
    resolver_cache: dict[str, str | None],
) -> tuple[list[Document], SourceEvidenceRecord | None]:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    nct_id = identification.get("nctId")
    if not nct_id:
        return [], None

    conditions = (protocol.get("conditionsModule") or {}).get("conditions") or []
    matched_conditions = []
    for condition in conditions:
        if is_junk_condition(condition):
            continue
        if _matching_targets(condition, targets):
            matched_conditions.append(normalize(condition))
    if not matched_conditions:
        return [], None

    interventions = (protocol.get("armsInterventionsModule") or {}).get("interventions") or []
    valid_drugs: dict[str, None] = {}
    for intervention in interventions:
        if intervention.get("type") != "DRUG":
            continue
        raw_name = intervention.get("name") or ""
        canonical = _validate_drug(
            raw_name,
            source="clinicaltrials",
            rejected=rejected_drugs,
            resolver_cache=resolver_cache,
        )
        if canonical:
            valid_drugs.setdefault(canonical, None)
    if not valid_drugs:
        return [], None

    design = protocol.get("designModule", {})
    status = protocol.get("statusModule", {})
    phase = normalize_phase(design.get("phases"))
    posted = status.get("studyFirstPostDateStruct", {}).get("date")
    started = status.get("startDateStruct", {}).get("date")
    study_date = parse_ctgov_date(posted) or parse_ctgov_date(started)
    evidence_type = _classify_trial_evidence(study)
    title = _study_title(study)
    url = f"https://clinicaltrials.gov/study/{nct_id}"

    documents: list[Document] = []
    relationships: list[dict] = []
    for drug in valid_drugs:
        for disease in matched_conditions:
            relationships.append(
                {
                    "drug": drug,
                    "disease": disease,
                    "evidence_type": evidence_type,
                    "status": "EVIDENCE",
                    "reason": "ClinicalTrials.gov DRUG intervention for the listed condition",
                }
            )
            documents.append(
                Document(
                    drug=drug,
                    disease=disease,
                    source="clinicaltrials",
                    source_id=nct_id,
                    phase=phase,
                    date=study_date,
                    url=url,
                    num_mentions=1,
                    evidence_type=evidence_type,
                )
            )

    record = SourceEvidenceRecord(
        query=query,
        source="clinicaltrials",
        source_id=nct_id,
        url=url,
        title=title,
        date=study_date,
        normalized_drugs=list(valid_drugs),
        normalized_diseases=matched_conditions,
        relationships=relationships,
    )
    return documents, record


def _dedupe_documents(documents: Iterable[Document]) -> list[Document]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[Document] = []
    for doc in documents:
        key = (doc.source, doc.source_id, doc.normalized_drug(), doc.normalized_disease())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(doc)
    return deduped


def _fetch_openfda_for_drug_safe(
    drug: str,
) -> tuple[str, list[ApprovedIndication], str | None]:
    try:
        return drug, openfda.ingest_drug(drug), None
    except httpx.HTTPError as exc:
        return drug, [], f"openFDA lookup failed for {drug}: {exc}"


def _fetch_openfda_indications(
    session: Session,
    drugs: Iterable[str],
    metadata: ResearchMetadata,
) -> tuple[list[ApprovedIndication], SourceAttempt]:
    """One openFDA label lookup per valid drug — run concurrently (I/O
    bound, no shared state between drugs) since a case can easily surface
    15-20+ valid drugs and these were previously the largest contributor to
    a case run's wall-clock time. DB writes happen back on the caller's
    session afterward, sequentially, since Session isn't thread-safe."""
    unique_drugs = sorted(set(drugs))
    indications: list[ApprovedIndication] = []
    outcomes: list[QueryOutcome] = []
    if not unique_drugs:
        return indications, SourceAttempt(source="openfda", status="not_attempted", queries_attempted=0)
    with ThreadPoolExecutor(max_workers=CASE_RESEARCH_FETCH_WORKERS) as pool:
        results = list(pool.map(_fetch_openfda_for_drug_safe, unique_drugs))
    for drug, fetched, error in results:
        if error:
            metadata.evidence_gaps.append(error)
            outcomes.append(QueryOutcome(query=drug, status="http_error", error=error))
            continue
        if not fetched:
            metadata.evidence_gaps.append(f"No openFDA label data found for {drug}.")
            outcomes.append(QueryOutcome(query=drug, status="success", items=[]))
            continue
        indications.extend(fetched)
        upsert_approved_indications(session, fetched)
        outcomes.append(QueryOutcome(query=drug, status="success", items=fetched))
    return indications, _aggregate_source_attempt("openfda", outcomes)


def _persist_records(session: Session, case_id: int, records: list[SourceEvidenceRecord]) -> None:
    for record in records:
        save_case_research_evidence(
            session,
            case_id=case_id,
            query=record.query,
            source=record.source,
            source_id=record.source_id,
            url=record.url,
            title=record.title,
            date=record.date,
            normalized_drugs=record.normalized_drugs,
            normalized_diseases=record.normalized_diseases,
            relationships=record.relationships,
        )


def filter_documents_by_valid_drug(documents: Iterable[Document]) -> list[Document]:
    """Authoritative drug-identity gate for documents that did NOT come
    through this module's own live-fetch path (i.e. the local/global
    discovery cache in `arbitrage.db`, used as a fallback when live
    research finds nothing for a case — see `run_runtime_case_research`'s
    docstring and app/main.py's `documents = runtime.documents or
    filter_documents_by_valid_drug(local_documents)`).

    Why this exists: `_validate_drug` above already gates every drug this
    module discovers live through `is_junk_drug_name` + RxNorm/allowlist
    resolution. Documents already sitting in the local cache were ingested
    by the older discovery pipeline (`app/ingestion/*.py`'s `discover()`),
    which never ran that gate — so NER artifacts from the bioRxiv/medRxiv
    CHEMICAL-label extraction (genetics/statistics terms like "snp"
    (single nucleotide polymorphism) or "prs" (polygenic risk score),
    mistagged as drugs) can sit there un-validated, and would otherwise
    surface as repurposing candidates whenever a case falls back to this
    cache. Applying the same `is_valid_medication_entity` authoritative
    check here (rather than inventing a second, weaker filter, or
    hardcoding the specific strings seen so far) closes that gap for any
    case, not just the one that happened to surface "snp"/"prs"."""
    documents = list(documents)
    distinct_names = sorted({doc.normalized_drug() for doc in documents})
    with ThreadPoolExecutor(max_workers=CASE_RESEARCH_FETCH_WORKERS) as pool:
        valid_flags = list(pool.map(is_valid_medication_entity, distinct_names))
    valid_names = {name for name, ok in zip(distinct_names, valid_flags) if ok}
    return [doc for doc in documents if doc.normalized_drug() in valid_names]


def select_relevant_local_documents(
    local_documents: Iterable[Document], *, targets: list[str]
) -> list[Document]:
    """The local/global-cache fallback used when live research comes back
    empty — restricted to (a) a validated real medication (see
    `filter_documents_by_valid_drug`) AND (b) a disease that actually
    matches one of this case's target conditions. Both gates matter: (a)
    alone would still let a validated drug's documents for a completely
    unrelated disease through; skipping straight to "the whole local
    corpus, case-filtered downstream by analyze_case" is exactly the
    "blindly dump the entire local corpus" failure mode this function
    exists to avoid — the relevance gate belongs in the research layer,
    explicit and auditable via research_metadata, not implicit in
    whatever analyze_case happens to filter out three call frames away."""
    valid = filter_documents_by_valid_drug(local_documents)
    return [doc for doc in valid if _matching_targets(doc.disease, targets)]


_STATUS_SEVERITY = {"rate_limited": 4, "timeout": 3, "http_error": 2, "parse_error": 1}


def _aggregate_source_attempt(source: str, outcomes: list[QueryOutcome]) -> SourceAttempt:
    """Rolls up every query attempted against one source this run into a
    single structured status (see SourceAttempt). The key rule: zero
    results is only ever reported as `"no_results"` when every attempted
    query actually completed successfully — if even one query hard-failed
    while the rest found nothing, the aggregate reports that failure
    (worst one, by severity) rather than "no_results", since a failed
    query might have found something a working one wouldn't have missed.
    That's what keeps an API outage from silently reading as "no evidence
    found" in research_metadata."""
    attempted = len(outcomes)
    if attempted == 0:
        return SourceAttempt(source=source, status="not_attempted", queries_attempted=0)

    total_items = sum(len(o.items) for o in outcomes)
    if total_items > 0:
        return SourceAttempt(source=source, status="success", results_found=total_items, queries_attempted=attempted)

    failures = [o for o in outcomes if o.status != "success"]
    if failures:
        worst = max(failures, key=lambda o: _STATUS_SEVERITY.get(o.status, 0))
        return SourceAttempt(
            source=source, status=worst.status, results_found=0, queries_attempted=attempted, error=worst.error
        )
    return SourceAttempt(source=source, status="no_results", results_found=0, queries_attempted=attempted)


def _is_hard_failure(attempt: SourceAttempt) -> bool:
    return attempt.status not in ("success", "no_results", "not_attempted")


def _fetch_round(
    queries: list[str], since: date
) -> tuple[dict[str, list[dict]], dict[str, list[dict]], list[QueryOutcome], list[QueryOutcome], list[QueryOutcome]]:
    """Fetches one round of queries (network I/O only) against all three
    live sources concurrently. Europe PMC and PubMed both feed into the
    same `papers_by_query` map — PubMed items carry `source: "MED"` (see
    app/ingestion/pubmed.py), so they parse through `_parse_paper` exactly
    like an Europe PMC MEDLINE-sourced record and dedup against Europe PMC
    automatically via the shared `seen_papers` keying in the caller, no
    PubMed-specific dedup needed."""
    with ThreadPoolExecutor(max_workers=CASE_RESEARCH_FETCH_WORKERS) as pool:
        epmc_futures = [pool.submit(_fetch_papers_for_query_safe, q, since) for q in queries]
        pubmed_futures = [pool.submit(_fetch_pubmed_for_query_safe, q, since) for q in queries]
        ctgov_futures = [pool.submit(_fetch_trials_for_query_safe, q) for q in queries]

        epmc_outcomes = [f.result() for f in epmc_futures]
        pubmed_outcomes = [f.result() for f in pubmed_futures]
        ctgov_outcomes = [f.result() for f in ctgov_futures]

    papers_by_query: dict[str, list[dict]] = {}
    for outcome in epmc_outcomes + pubmed_outcomes:
        papers_by_query.setdefault(outcome.query, []).extend(outcome.items)

    trials_by_query: dict[str, list[dict]] = {}
    for outcome in ctgov_outcomes:
        trials_by_query.setdefault(outcome.query, []).extend(outcome.items)

    return papers_by_query, trials_by_query, epmc_outcomes, pubmed_outcomes, ctgov_outcomes


def run_runtime_case_research(
    session: Session,
    *,
    case_id: int,
    primary_condition: str,
    comorbidities: list[str],
    current_medications: list[str],
    local_approved: list[ApprovedIndication],
    local_documents: list[Document] | None = None,
) -> RuntimeResearchResult:
    """Retrieve and cache live, case-specific evidence.

    Fallback semantics (see PROGRESS.md's retrieval-layer audit): an API
    failure and a genuine "searched, found nothing relevant" are never
    conflated. `local_documents` (the global discovery cache) is only
    consulted at all once live retrieval across every source has already
    finished — success or failure — and even then only validated,
    case-relevant rows are used (see `select_relevant_local_documents`),
    tagged in `metadata.used_local_fallback`/`local_fallback_reason` so a
    caller can never mistake cached secondary evidence for a fresh live
    result.
    """
    tier1_queries = generate_case_queries(primary_condition, comorbidities, current_medications)
    metadata = ResearchMetadata(queries=tier1_queries)
    targets = _target_conditions(primary_condition, comorbidities)
    since = date.today() - timedelta(days=CASE_RESEARCH_TIME_WINDOW_DAYS)

    rejected_drugs: dict[tuple[str, str, str | None], RejectedDrug] = {}
    resolver_cache: dict[str, str | None] = {}
    case_drugs = _case_medication_drugs(
        current_medications, rejected=rejected_drugs, resolver_cache=resolver_cache
    )

    papers_by_query, trials_by_query, epmc_outcomes, pubmed_outcomes, ctgov_outcomes = _fetch_round(
        tier1_queries, since
    )
    all_queries = list(tier1_queries)

    # Broader-query retry (Step 3/5 of the retrieval audit): only fires
    # when tier-1's exact-phrase queries returned literally zero *raw*
    # items from every source — a real, confirmed failure mode when a
    # case's free-text condition is a verbose ontology-style label whose
    # exact phrase never appears in literature verbatim (see
    # _broaden_term's docstring). Deliberately keyed on raw item count,
    # not post-relevance-filter document count: a query that found real
    # papers which then failed the disease/therapeutic-language filters is
    # a different, legitimate outcome ("retrieved but not relevant
    # evidence") that broadening again wouldn't fix and shouldn't retry.
    tier1_raw_items = sum(len(v) for v in papers_by_query.values()) + sum(len(v) for v in trials_by_query.values())
    if tier1_raw_items == 0:
        broad_queries = [
            q
            for q in generate_broad_case_queries(primary_condition, comorbidities, current_medications)
            if q not in papers_by_query and q not in trials_by_query
        ]
        if broad_queries:
            metadata.broadened_queries = broad_queries
            b_papers, b_trials, b_epmc, b_pubmed, b_ctgov = _fetch_round(broad_queries, since)
            papers_by_query.update(b_papers)
            trials_by_query.update(b_trials)
            epmc_outcomes += b_epmc
            pubmed_outcomes += b_pubmed
            ctgov_outcomes += b_ctgov
            all_queries += broad_queries

            # A broadened query is pointless on its own if the relevance
            # filter below still requires the ORIGINAL verbose target text
            # (e.g. "diabetes type 2 adult non insulin independent") to
            # appear verbatim in a paper/trial — real evidence almost never
            # phrases it that way. Add the same simplified terms used to
            # broaden the queries as additional acceptable match targets,
            # so a paper found via the broader query can actually pass the
            # disease-relevance check too, not just the retrieval step.
            for raw in [primary_condition] + comorbidities:
                broad_target = _broaden_term(raw)
                if broad_target and broad_target not in targets:
                    targets.append(broad_target)

    europepmc_attempt = _aggregate_source_attempt("europepmc", epmc_outcomes)
    pubmed_attempt = _aggregate_source_attempt("pubmed", pubmed_outcomes)
    ctgov_attempt = _aggregate_source_attempt("clinicaltrials", ctgov_outcomes)

    for outcome in epmc_outcomes:
        if outcome.status != "success":
            metadata.evidence_gaps.append(f"Europe PMC lookup failed for query {outcome.query!r}: {outcome.error}")
    for outcome in pubmed_outcomes:
        if outcome.status != "success":
            metadata.evidence_gaps.append(f"PubMed lookup failed for query {outcome.query!r}: {outcome.error}")
    for outcome in ctgov_outcomes:
        if outcome.status != "success":
            metadata.evidence_gaps.append(
                f"ClinicalTrials.gov lookup failed for query {outcome.query!r}: {outcome.error}"
            )

    records: list[SourceEvidenceRecord] = []
    live_documents: list[Document] = []
    seen_papers: set[str] = set()
    seen_trials: set[str] = set()

    for query in all_queries:
        if len(seen_papers) < CASE_RESEARCH_MAX_PAPERS:
            for paper in papers_by_query.get(query, []):
                source_and_id = _publication_source_and_id(paper)
                if source_and_id is None:
                    continue
                source, source_id = source_and_id
                key = f"{source}:{source_id}"
                if key in seen_papers:
                    continue
                docs, record = _parse_paper(
                    paper,
                    query=query,
                    targets=targets,
                    case_drugs=case_drugs,
                    metadata=metadata,
                )
                if record is None:
                    continue
                seen_papers.add(key)
                records.append(record)
                live_documents.extend(docs)
                if len(seen_papers) >= CASE_RESEARCH_MAX_PAPERS:
                    break

        if len(seen_trials) < CASE_RESEARCH_MAX_TRIALS:
            for study in trials_by_query.get(query, []):
                nct_id = (
                    study.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("nctId")
                )
                if not nct_id or nct_id in seen_trials:
                    continue
                docs, record = _parse_trial(
                    study,
                    query=query,
                    targets=targets,
                    metadata=metadata,
                    rejected_drugs=rejected_drugs,
                    resolver_cache=resolver_cache,
                )
                if record is None:
                    continue
                seen_trials.add(nct_id)
                records.append(record)
                live_documents.extend(docs)
                if len(seen_trials) >= CASE_RESEARCH_MAX_TRIALS:
                    break

        if len(seen_papers) >= CASE_RESEARCH_MAX_PAPERS and len(seen_trials) >= CASE_RESEARCH_MAX_TRIALS:
            break

    live_documents = _dedupe_documents(live_documents)

    # --- fallback decision (Step 5): live evidence, or explicitly-marked
    # cached local evidence, or an honest zero-signal result. Never a
    # silent substitution. ---
    final_documents = live_documents
    used_local_fallback = False
    local_fallback_reason: str | None = None
    if not live_documents and local_documents:
        relevant_local = select_relevant_local_documents(local_documents, targets=targets)
        if relevant_local:
            final_documents = relevant_local
            used_local_fallback = True
            hard_failures = [a for a in (europepmc_attempt, pubmed_attempt, ctgov_attempt) if _is_hard_failure(a)]
            if hard_failures:
                names = ", ".join(a.source for a in hard_failures)
                local_fallback_reason = (
                    f"Live sources ({names}) were unavailable this run — using cached, "
                    "validated local evidence as a secondary source. This may not reflect "
                    "the most current research; re-check when live sources recover."
                )
            else:
                local_fallback_reason = (
                    "Live search completed successfully but found no case-relevant "
                    "results — checked cached local evidence and used validated, "
                    "case-relevant signals from it instead."
                )

    valid_drugs = sorted({doc.normalized_drug() for doc in final_documents} | set(case_drugs))
    runtime_approved, openfda_attempt = _fetch_openfda_indications(session, valid_drugs, metadata)
    all_approved = local_approved + runtime_approved

    approved_index = build_approved_index(all_approved)
    for doc in final_documents:
        if is_already_approved(doc.drug, doc.disease, approved_index):
            _add_rejected_relationship(
                metadata,
                drug=doc.drug,
                disease=doc.disease,
                source=doc.source,
                source_id=doc.source_id,
                evidence_type=doc.evidence_type or "UNKNOWN",
                reason="known indication, not a repurposing candidate",
            )

    metadata.papers_retrieved = len(seen_papers)
    metadata.trials_retrieved = len(seen_trials)
    metadata.valid_drugs = valid_drugs
    metadata.normalized_drugs = valid_drugs
    metadata.rejected_drugs = sorted(
        rejected_drugs.values(), key=lambda r: (r.source or "", r.raw_name, r.reason)
    )
    metadata.valid_drug_disease_relationships = len(
        {
            (doc.normalized_drug(), doc.normalized_disease(), doc.source, doc.source_id)
            for doc in final_documents
        }
    )
    metadata.source_counts = dict(Counter(record.source for record in records))
    metadata.source_statuses = [europepmc_attempt, pubmed_attempt, ctgov_attempt, openfda_attempt]
    metadata.used_local_fallback = used_local_fallback
    metadata.local_fallback_reason = local_fallback_reason

    # Only claim "no relevant X was retrieved" when that source's own
    # aggregate status says it actually searched cleanly (success/
    # no_results) — if it hard-failed, the per-query error messages above
    # already say so, and adding this would be exactly the "silently
    # converted an API failure into 'no evidence found'" bug this audit
    # exists to prevent.
    if metadata.papers_retrieved == 0 and not _is_hard_failure(europepmc_attempt) and not _is_hard_failure(pubmed_attempt):
        metadata.evidence_gaps.append("No relevant publications were retrieved for this case.")
    if metadata.trials_retrieved == 0 and not _is_hard_failure(ctgov_attempt):
        metadata.evidence_gaps.append("No relevant ClinicalTrials.gov studies were retrieved for this case.")
    if not final_documents and not used_local_fallback:
        metadata.evidence_gaps.append("No evidence-bearing drug-disease relationships passed validation.")

    _persist_records(session, case_id, records)

    return RuntimeResearchResult(
        documents=final_documents,
        approved_indications=all_approved,
        metadata=metadata,
        records=records,
        paper_source_ids=seen_papers,
        trial_source_ids=seen_trials,
    )
