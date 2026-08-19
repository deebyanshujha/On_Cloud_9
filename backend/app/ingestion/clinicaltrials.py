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
from typing import Iterator

import httpx

from app.schemas.document import Document

CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

# Keep the payload small: we only need these fields for the shared schema.
FIELDS = "NCTId,Condition,Phase,StudyFirstPostDate,StartDate"

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
