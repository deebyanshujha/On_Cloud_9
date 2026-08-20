"""ClinicalTrials.gov ingestion (Step 3).

Fetches studies where a given drug is listed as an intervention, and
normalizes each (study, condition) pair into the shared Document shape
from shared/schema.md. One study can list several conditions — we emit
one Document per condition, since each is a separate drug-disease
observation.

No API key needed. Docs: https://clinicaltrials.gov/data-api/api
"""
from __future__ import annotations

from datetime import date as date_
from datetime import timedelta
from typing import Iterator

import httpx

from app.core.config import MAX_RESULTS_PER_SOURCE, PAGE_SIZE, TIME_WINDOW_DAYS
from app.core.drug_normalization import is_junk_drug_name, normalize_drug_name
from app.schemas.document import Document

CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

# Keep the payload small: we only need these fields for the shared schema.
FIELDS = "NCTId,Condition,Phase,StudyFirstPostDate,StartDate"

# Discovery mode also needs the drug/intervention names themselves, since
# there's no longer a caller-supplied drug to attach to each condition.
DISCOVERY_FIELDS = FIELDS + ",InterventionName,InterventionType"

PHASE_LABELS = {
    "NA": "not applicable",
    "EARLY_PHASE1": "early phase 1",
    "PHASE1": "phase 1",
    "PHASE2": "phase 2",
    "PHASE3": "phase 3",
    "PHASE4": "phase 4",
}
PHASE_RANK = {
    "not applicable": 0,
    "early phase 1": 1,
    "phase 1": 2,
    "phase 2": 3,
    "phase 3": 4,
    "phase 4": 5,
}


def normalize_phase(raw_phases: list[str] | None) -> str | None:
    """A study can list multiple phases (e.g. a Phase 2/3 trial). We keep
    the highest one since that's what the scoring engine's weights key
    off of."""
    if not raw_phases:
        return None
    labels = [PHASE_LABELS.get(p, None) for p in raw_phases]
    labels = [label for label in labels if label]
    if not labels:
        return None
    return max(labels, key=lambda label: PHASE_RANK.get(label, 0))


def parse_ctgov_date(raw: str | None) -> date_ | None:
    """ClinicalTrials.gov dates are 'YYYY-MM-DD', 'YYYY-MM', or just 'YYYY'.
    Missing month/day default to January / the 1st."""
    if not raw:
        return None
    parts = raw.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    day = int(parts[2]) if len(parts) > 2 else 1
    try:
        return date_(year, month, day)
    except ValueError:
        return date_(year, month, 1)


def fetch_raw_studies(
    drug: str, page_size: int = 50, max_studies: int = 200
) -> Iterator[dict]:
    """Yields raw study dicts from the ClinicalTrials.gov v2 API for a
    given drug/intervention name, following pagination until max_studies
    is reached or the source runs out of pages."""
    params = {"query.intr": drug, "pageSize": page_size, "fields": FIELDS}
    fetched = 0

    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(CTGOV_STUDIES_URL, params=params)
            response.raise_for_status()
            payload = response.json()

            for study in payload.get("studies", []):
                yield study
                fetched += 1
                if fetched >= max_studies:
                    return

            next_token = payload.get("nextPageToken")
            if not next_token:
                return
            params["pageToken"] = next_token


def parse_study_to_documents(study: dict, queried_drug: str) -> list[Document]:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})

    nct_id = identification.get("nctId")
    if not nct_id:
        return []

    conditions = conditions_module.get("conditions") or []
    if not conditions:
        return []

    phase = normalize_phase(design.get("phases"))

    posted = status.get("studyFirstPostDateStruct", {}).get("date")
    started = status.get("startDateStruct", {}).get("date")
    doc_date = parse_ctgov_date(posted) or parse_ctgov_date(started)

    url = f"https://clinicaltrials.gov/study/{nct_id}"

    return [
        Document(
            drug=queried_drug,
            disease=condition,
            source="clinicaltrials",
            source_id=nct_id,
            phase=phase,
            date=doc_date,
            url=url,
            num_mentions=1,
            evidence_type="CLINICAL_TRIAL",
        )
        for condition in conditions
    ]


def ingest_drug(drug: str, max_studies: int = 200) -> list[Document]:
    """Fetches and normalizes all trials for one drug. Does not touch the
    database — callers decide whether/how to store the result."""
    documents: list[Document] = []
    for study in fetch_raw_studies(drug, max_studies=max_studies):
        documents.extend(parse_study_to_documents(study, queried_drug=drug))
    return documents


# --- Discovery mode (Step 10) ----------------------------------------------
# Instead of requiring a drug name as input, query broadly by recency across
# ALL interventional studies and extract drug names FROM the results
# (armsInterventionsModule interventions of type "DRUG"), the same way
# extract_diseases() in biorxiv.py pulls disease names out of free text
# rather than requiring them as input.


def fetch_raw_studies_broad(
    since: date_ | None = None,
    page_size: int = PAGE_SIZE,
    max_studies: int = MAX_RESULTS_PER_SOURCE,
) -> Iterator[dict]:
    """Yields raw study dicts for ALL studies first posted on/after `since`
    (default: TIME_WINDOW_DAYS ago), most recent first, following
    pagination until max_studies is reached or the source runs out of
    pages. No drug/intervention filter — this is the discovery entry point;
    drug names are extracted from each study's interventions afterward."""
    since = since or (date_.today() - timedelta(days=TIME_WINDOW_DAYS))
    params = {
        "pageSize": page_size,
        "fields": DISCOVERY_FIELDS,
        "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{since.isoformat()},MAX]",
        "sort": "StudyFirstPostDate:desc",
    }
    fetched = 0

    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(CTGOV_STUDIES_URL, params=params)
            response.raise_for_status()
            payload = response.json()

            for study in payload.get("studies", []):
                yield study
                fetched += 1
                if fetched >= max_studies:
                    return

            next_token = payload.get("nextPageToken")
            if not next_token:
                return
            params["pageToken"] = next_token


def extract_drug_names(study: dict) -> list[str]:
    """Pulls every DRUG-type intervention name off a study and normalizes
    it (see app/core/drug_normalization.py) — these are the drug names
    discovery mode has to work with instead of a caller-supplied drug
    argument. Normalizing here, not just in the known-drugs cache, is what
    keeps `"Dose reduction of lezertinib"` and a plain `"lezertinib"`
    intervention from becoming two different Document.drug values (and
    thus two different signals) instead of merging into one."""
    protocol = study.get("protocolSection", {})
    interventions = (protocol.get("armsInterventionsModule", {}) or {}).get(
        "interventions"
    ) or []
    seen: dict[str, None] = {}
    for i in interventions:
        if i.get("type") != "DRUG" or not i.get("name"):
            continue
        if is_junk_drug_name(i["name"]):
            continue
        normalized = normalize_drug_name(i["name"])
        if normalized:
            seen[normalized] = None
    return list(seen)


def parse_study_to_documents_discovery(study: dict) -> list[Document]:
    """Discovery-mode version of parse_study_to_documents: instead of
    pairing every condition with one caller-supplied drug, pairs every
    condition with every DRUG-type intervention found on the study itself.
    A study with 2 drug arms and 2 conditions yields up to 4 documents —
    normal for combination-therapy trials, and no worse than treating each
    arm as its own signal candidate."""
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})

    nct_id = identification.get("nctId")
    if not nct_id:
        return []

    conditions = conditions_module.get("conditions") or []
    drug_names = extract_drug_names(study)
    if not conditions or not drug_names:
        return []

    phase = normalize_phase(design.get("phases"))

    posted = status.get("studyFirstPostDateStruct", {}).get("date")
    started = status.get("startDateStruct", {}).get("date")
    doc_date = parse_ctgov_date(posted) or parse_ctgov_date(started)

    url = f"https://clinicaltrials.gov/study/{nct_id}"

    return [
        Document(
            drug=drug_name,
            disease=condition,
            source="clinicaltrials",
            source_id=nct_id,
            phase=phase,
            date=doc_date,
            url=url,
            num_mentions=1,
            evidence_type="CLINICAL_TRIAL",
        )
        for drug_name in drug_names
        for condition in conditions
    ]


def discover(
    since: date_ | None = None, max_studies: int = MAX_RESULTS_PER_SOURCE
) -> list[Document]:
    """Discovery-mode ingestion: scans recent ClinicalTrials.gov studies
    (no drug filter), extracts every (drug, condition) pair found, and
    returns them as Document objects. Does not touch the database or the
    known-drugs cache — callers decide whether/how to store the result."""
    documents: list[Document] = []
    for study in fetch_raw_studies_broad(since=since, max_studies=max_studies):
        documents.extend(parse_study_to_documents_discovery(study))
    return documents
