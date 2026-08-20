"""bioRxiv/medRxiv ingestion + NER extraction (Step 6).

Unlike ClinicalTrials.gov, bioRxiv and medRxiv don't offer a public
full-text/keyword search API of their own — their official API
(api.biorxiv.org) only lists papers by date range or looks up a single
paper by DOI, with no way to ask "give me papers mentioning metformin."
Europe PMC (https://europepmc.org, EMBL-EBI, free/no-login) indexes the
same bioRxiv/medRxiv preprints — every result here is still a genuine
bioRxiv or medRxiv paper (title, DOI, abstract, publish date all point back
to the original preprint) — and its search API supports keyword queries
plus a `PUBLISHER` filter, which is what makes "find bioRxiv/medRxiv papers
about drug X" possible at all. This is a judgment call worth knowing about,
not a silent substitution — see PROGRESS.md.

Since bioRxiv/medRxiv abstracts are free text (unlike ClinicalTrials.gov's
structured `Condition` field), figuring out which diseases a paper is
about requires NLP: this module runs scispaCy's `en_ner_bc5cdr_md` model
(trained on the BC5CDR corpus for biomedical NER) over each matching
title+abstract and pulls out DISEASE entities. No LLM APIs — this is a
local, open-source NER model per the project's explicit constraint.

No API key needed. Docs: https://europepmc.org/RestfulWebService
"""
from __future__ import annotations

import re
from datetime import date as date_
from datetime import timedelta
from functools import lru_cache
from typing import Iterator, Protocol

import httpx

from app.core.config import MAX_RESULTS_PER_SOURCE, PAGE_SIZE, TIME_WINDOW_DAYS
from app.core.drug_normalization import normalize_drug_name
from app.schemas.document import Document

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Restricting to these two publishers is what keeps this a bioRxiv/medRxiv
# ingestion source rather than "any preprint server Europe PMC indexes"
# (it also indexes Research Square, SSRN, etc.).
ALLOWED_PUBLISHERS = {"biorxiv": "biorxiv", "medrxiv": "medrxiv"}

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

NER_MODEL_NAME = "en_ner_bc5cdr_md"


class NerModel(Protocol):
    """Structural type for whatever we pass as `nlp` — either a real
    spaCy `Language` (loaded via load_ner_model()) or a lightweight fake
    used in tests. Only needs to support `nlp(text)` returning something
    with `.ents`, each with `.text` and `.label_`."""

    def __call__(self, text: str): ...


@lru_cache(maxsize=1)
def load_ner_model() -> NerModel:
    """Loads the scispaCy disease/chemical NER model once and caches it —
    loading it per-call would be far too slow. Requires `en_ner_bc5cdr_md`
    to be installed (see backend/requirements.txt)."""
    import spacy

    try:
        return spacy.load(NER_MODEL_NAME)
    except OSError as exc:
        raise RuntimeError(
            f"scispaCy model '{NER_MODEL_NAME}' is not installed. Install it with:\n"
            f'  pip install "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/'
            f'releases/v0.5.4/{NER_MODEL_NAME}-0.5.4.tar.gz"'
        ) from exc


def strip_html(text: str) -> str:
    """Europe PMC's abstractText includes structural tags like
    <h4>Background</h4> — strip them so NER sees plain prose."""
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def extract_entities(nlp: NerModel, text: str, label: str) -> list[str]:
    """Runs NER over `text` and returns unique, normalized entity strings
    for the given label (lowercased, whitespace-collapsed), in first-seen
    order. `en_ner_bc5cdr_md` supports DISEASE and CHEMICAL labels."""
    doc = nlp(text)
    seen: dict[str, None] = {}
    for ent in doc.ents:
        if ent.label_ != label:
            continue
        normalized = " ".join(ent.text.strip().lower().split())
        if normalized:
            seen[normalized] = None
    return list(seen)


def extract_diseases(nlp: NerModel, text: str) -> list[str]:
    """Unique, normalized DISEASE entity strings found in `text`."""
    return extract_entities(nlp, text, "DISEASE")


def extract_drugs(nlp: NerModel, text: str) -> list[str]:
    """Unique, normalized CHEMICAL entity strings found in `text` — used by
    discovery mode to find drug mentions instead of requiring a
    caller-supplied drug name."""
    return extract_entities(nlp, text, "CHEMICAL")


def fetch_raw_preprints(drug: str, page_size: int = 25, max_results: int = 100) -> Iterator[dict]:
    """Yields raw Europe PMC result dicts for bioRxiv/medRxiv preprints
    mentioning `drug`, following cursor pagination until max_results is
    reached or results run out."""
    query = f'{drug} AND SRC:PPR AND (PUBLISHER:"bioRxiv" OR PUBLISHER:"medRxiv")'
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": page_size,
        "cursorMark": "*",
    }
    fetched = 0

    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(EUROPEPMC_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()

            results = payload.get("resultList", {}).get("result", [])
            for result in results:
                yield result
                fetched += 1
                if fetched >= max_results:
                    return

            if not results:
                return

            next_cursor = payload.get("nextCursorMark")
            if not next_cursor or next_cursor == params["cursorMark"]:
                return
            params["cursorMark"] = next_cursor


def parse_publication_date(raw: str | None) -> date_ | None:
    """Europe PMC dates are 'YYYY-MM-DD'."""
    if not raw:
        return None
    try:
        year, month, day = (int(part) for part in raw.split("-"))
        return date_(year, month, day)
    except ValueError:
        return None


def parse_preprint_to_documents(
    paper: dict, queried_drug: str, nlp: NerModel
) -> list[Document]:
    doi = paper.get("doi")
    if not doi:
        return []

    publisher_raw = (paper.get("bookOrReportDetails") or {}).get("publisher", "")
    source = ALLOWED_PUBLISHERS.get(publisher_raw.strip().lower())
    if source is None:
        # Not actually a bioRxiv/medRxiv result (shouldn't happen given the
        # PUBLISHER filter in the query, but don't trust it blindly).
        return []

    title = paper.get("title", "")
    abstract = strip_html(paper.get("abstractText", ""))
    text = f"{title}. {abstract}".strip()
    if not text:
        return []

    diseases = extract_diseases(nlp, text)
    if not diseases:
        return []

    doc_date = parse_publication_date(paper.get("firstPublicationDate"))
    url = f"https://doi.org/{doi}"

    return [
        Document(
            drug=queried_drug,
            disease=disease,
            source=source,
            source_id=doi,
            phase=None,
            date=doc_date,
            url=url,
            num_mentions=1,
            evidence_type="HUMAN_STUDY" if source == "medrxiv" else "PRECLINICAL",
        )
        for disease in diseases
    ]


def ingest_drug(drug: str, max_results: int = 50) -> list[Document]:
    """Fetches bioRxiv/medRxiv preprints mentioning `drug`, runs NER over
    each, and returns Document objects — one per (paper, extracted
    disease) pair. Does not touch the database — callers decide
    whether/how to store the result."""
    nlp = load_ner_model()
    documents: list[Document] = []
    for paper in fetch_raw_preprints(drug, max_results=max_results):
        documents.extend(parse_preprint_to_documents(paper, queried_drug=drug, nlp=nlp))
    return documents


# --- Discovery mode (Step 10) ----------------------------------------------
# Same shift as clinicaltrials.py: search broadly (within the existing
# bioRxiv/medRxiv PUBLISHER filter and a recency window) instead of
# requiring a known drug name in the query, then run NER over each
# abstract for BOTH labels — CHEMICAL (candidate drug mentions) and DISEASE
# — instead of only extracting diseases from abstracts already known to
# mention a given drug.


def fetch_raw_preprints_broad(
    since: date_ | None = None,
    page_size: int = PAGE_SIZE,
    max_results: int = MAX_RESULTS_PER_SOURCE,
) -> Iterator[dict]:
    """Yields raw Europe PMC result dicts for bioRxiv/medRxiv preprints
    published on/after `since` (default: TIME_WINDOW_DAYS ago) — no drug
    keyword in the query, just the same PUBLISHER filter plus a recency
    window. Follows cursor pagination until max_results is reached or
    results run out."""
    since = since or (date_.today() - timedelta(days=TIME_WINDOW_DAYS))
    query = (
        f'SRC:PPR AND (PUBLISHER:"bioRxiv" OR PUBLISHER:"medRxiv") '
        f'AND FIRST_PDATE:[{since.isoformat()} TO {date_.today().isoformat()}]'
    )
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": page_size,
        "cursorMark": "*",
    }
    fetched = 0

    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(EUROPEPMC_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()

            results = payload.get("resultList", {}).get("result", [])
            for result in results:
                yield result
                fetched += 1
                if fetched >= max_results:
                    return

            if not results:
                return

            next_cursor = payload.get("nextCursorMark")
            if not next_cursor or next_cursor == params["cursorMark"]:
                return
            params["cursorMark"] = next_cursor


def parse_preprint_to_documents_discovery(paper: dict, nlp: NerModel) -> list[Document]:
    """Discovery-mode version of parse_preprint_to_documents: instead of
    pairing every extracted disease with one caller-supplied drug, runs NER
    for both CHEMICAL (candidate drugs) and DISEASE entities and pairs every
    drug found with every disease found in the same abstract."""
    doi = paper.get("doi")
    if not doi:
        return []

    publisher_raw = (paper.get("bookOrReportDetails") or {}).get("publisher", "")
    source = ALLOWED_PUBLISHERS.get(publisher_raw.strip().lower())
    if source is None:
        return []

    title = paper.get("title", "")
    abstract = strip_html(paper.get("abstractText", ""))
    text = f"{title}. {abstract}".strip()
    if not text:
        return []

    raw_drugs = extract_drugs(nlp, text)
    diseases = extract_diseases(nlp, text)
    # Normalize NER-extracted drug mentions the same way discovered
    # ClinicalTrials.gov intervention names are normalized (see
    # app/core/drug_normalization.py), so e.g. "metformin" and "metformin
    # hydrochloride" mentioned in the same corpus merge into one
    # Document.drug value instead of becoming separate signals.
    drugs: dict[str, None] = {}
    for raw in raw_drugs:
        normalized = normalize_drug_name(raw)
        if normalized:
            drugs[normalized] = None
    drugs = list(drugs)
    if not drugs or not diseases:
        return []

    doc_date = parse_publication_date(paper.get("firstPublicationDate"))
    url = f"https://doi.org/{doi}"

    return [
        Document(
            drug=drug,
            disease=disease,
            source=source,
            source_id=doi,
            phase=None,
            date=doc_date,
            url=url,
            num_mentions=1,
            evidence_type="HUMAN_STUDY" if source == "medrxiv" else "PRECLINICAL",
        )
        for drug in drugs
        for disease in diseases
    ]


def discover(
    since: date_ | None = None,
    max_results: int = MAX_RESULTS_PER_SOURCE,
    nlp: NerModel | None = None,
) -> list[Document]:
    """Discovery-mode ingestion: scans recent bioRxiv/medRxiv preprints (no
    drug keyword), runs NER over each abstract, and returns every
    (drug, disease) pair found as Document objects. Does not touch the
    database or the known-drugs cache — callers decide whether/how to store
    the result."""
    nlp = nlp or load_ner_model()
    documents: list[Document] = []
    for paper in fetch_raw_preprints_broad(since=since, max_results=max_results):
        documents.extend(parse_preprint_to_documents_discovery(paper, nlp=nlp))
    return documents
