"""PubMed (NCBI E-utilities) ingestion — an independent literature source
alongside Europe PMC, not a replacement for it.

Why PubMed in addition to Europe PMC: Europe PMC already indexes MEDLINE
(PubMed) content, but its own search/relevance ranking and abstract
availability can differ from querying PubMed directly — a case's live
research is more resilient when it isn't dependent on a single search
index's uptime or query-matching behavior. Two independent indexes over
overlapping-but-not-identical content also means one source's outage
doesn't leave a case's research vocabulary silently one-source's worth of
literature short. See app/core/runtime_research.py for how results from
this module are deduplicated against Europe PMC's (same PMID -> same
identity, handled automatically by that module's existing dedup key).

No scraping — this talks to the official, free, no-login E-utilities REST
API (ESearch for PMIDs, EFetch for full records: title/abstract/pub
date/publication types/DOI). Docs:
https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""
from __future__ import annotations

import re
import threading
from datetime import date as date_
from xml.etree import ElementTree

import httpx

from app.core.config import (
    CASE_RESEARCH_MAX_RETRIES,
    CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
    NCBI_API_KEY,
    PUBMED_MAX_CONCURRENT_REQUESTS,
)
from app.core.http_fetch import FetchOutcome, get_with_retry

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# NCBI's documented rate limit is 3 req/sec without an API key (10/sec
# with one). This bounds concurrent PubMed requests process-wide,
# independent of the general case-research thread pool size, so a case
# with many queries can't trip it.
_RATE_LIMIT_SEMAPHORE = threading.Semaphore(PUBMED_MAX_CONCURRENT_REQUESTS)

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _api_params(extra: dict) -> dict:
    params = dict(extra)
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def _month_to_int(raw: str | None) -> int:
    if not raw:
        return 1
    raw = raw.strip().lower()
    if raw.isdigit():
        return max(1, min(12, int(raw)))
    return _MONTH_NAMES.get(raw[:3], 1)


def _parse_pub_date(article_elem: ElementTree.Element) -> str | None:
    pub_date = article_elem.find("./Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year = pub_date.findtext("Year")
        if year and year.isdigit():
            month = _month_to_int(pub_date.findtext("Month"))
            day_raw = pub_date.findtext("Day")
            day = int(day_raw) if day_raw and day_raw.isdigit() else 1
            try:
                return date_(int(year), month, day).isoformat()
            except ValueError:
                return date_(int(year), month, 1).isoformat()
        medline_date = pub_date.findtext("MedlineDate")
        if medline_date:
            match = re.search(r"(19|20)\d{2}", medline_date)
            if match:
                return date_(int(match.group()), 1, 1).isoformat()
    article_date = article_elem.find("./ArticleDate")
    if article_date is not None:
        year = article_date.findtext("Year")
        if year and year.isdigit():
            month = _month_to_int(article_date.findtext("Month"))
            day_raw = article_date.findtext("Day")
            day = int(day_raw) if day_raw and day_raw.isdigit() else 1
            try:
                return date_(int(year), month, day).isoformat()
            except ValueError:
                return date_(int(year), month, 1).isoformat()
    return None


def _element_text(elem: ElementTree.Element | None) -> str:
    if elem is None:
        return ""
    return "".join(elem.itertext())


def _parse_pubmed_article(pubmed_article: ElementTree.Element) -> dict | None:
    """Converts one <PubmedArticle> into the same paper-dict shape
    app/core/runtime_research.py already knows how to parse for Europe PMC
    results (title/abstractText/firstPublicationDate/pubTypeList/doi),
    with source="MED" so it resolves to the "pubmed" source exactly like an
    Europe PMC record whose own `source` field is "MED" — this is what
    makes cross-source dedup (same PMID from both Europe PMC and PubMed)
    work automatically via the existing seen_papers keying, with no
    PubMed-specific dedup logic needed."""
    citation = pubmed_article.find("./MedlineCitation")
    if citation is None:
        return None
    pmid = citation.findtext("PMID")
    if not pmid:
        return None

    article = citation.find("./Article")
    if article is None:
        return None

    title = _element_text(article.find("./ArticleTitle")).strip()
    abstract_parts = [
        _element_text(node).strip()
        for node in article.findall("./Abstract/AbstractText")
    ]
    abstract = " ".join(part for part in abstract_parts if part)

    pub_types = [
        (t.text or "").strip()
        for t in article.findall("./PublicationTypeList/PublicationType")
        if (t.text or "").strip()
    ]

    doi = None
    for elocation in article.findall("./ELocationID"):
        if elocation.get("EIdType") == "doi" and elocation.text:
            doi = elocation.text.strip()
            break
    if not doi:
        pubmed_data = pubmed_article.find("./PubmedData")
        if pubmed_data is not None:
            for article_id in pubmed_data.findall("./ArticleIdList/ArticleId"):
                if article_id.get("IdType") == "doi" and article_id.text:
                    doi = article_id.text.strip()
                    break

    return {
        "pmid": pmid,
        "doi": doi,
        "source": "MED",
        "title": title,
        "abstractText": abstract,
        "firstPublicationDate": _parse_pub_date(article),
        "pubTypeList": {"pubType": pub_types},
    }


def _esearch(client: httpx.Client, query: str, *, since: date_, retstart: int, retmax: int) -> FetchOutcome:
    with _RATE_LIMIT_SEMAPHORE:
        return get_with_retry(
            client,
            ESEARCH_URL,
            _api_params(
                {
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retstart": retstart,
                    "retmax": retmax,
                    "datetype": "pdat",
                    "mindate": since.strftime("%Y/%m/%d"),
                    "maxdate": date_.today().strftime("%Y/%m/%d"),
                }
            ),
            max_retries=CASE_RESEARCH_MAX_RETRIES,
            backoff_seconds=CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
        )


def _efetch(client: httpx.Client, pmids: list[str]) -> FetchOutcome:
    with _RATE_LIMIT_SEMAPHORE:
        return get_with_retry(
            client,
            EFETCH_URL,
            _api_params({"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml"}),
            max_retries=CASE_RESEARCH_MAX_RETRIES,
            backoff_seconds=CASE_RESEARCH_RETRY_BACKOFF_SECONDS,
        )


def search_pubmed(
    query: str,
    *,
    since: date_,
    page_size: int,
    max_results: int,
) -> tuple[list[dict], FetchOutcome]:
    """ESearch for PMIDs matching `query`, then EFetch the full records for
    those PMIDs in one batched call. Returns (papers, outcome) — `papers`
    is empty and `outcome.status` explains why whenever anything short of
    a clean "search ran, here are 0-N results" happens (timeout,
    rate-limited, http_error, parse_error). A clean empty search returns
    `([], FetchOutcome(status="success", ...))` — the caller (runtime_
    research.py) is what turns "success with 0 items" into the
    "no_results" status category, same as it does for Europe PMC/CT.gov,
    so all three sources classify that distinction identically in one
    place rather than three slightly different ways."""
    with httpx.Client(timeout=30.0) as client:
        search_outcome = _esearch(client, query, since=since, retstart=0, retmax=min(page_size, max_results))
        if search_outcome.status != "success":
            return [], search_outcome

        try:
            payload = search_outcome.response.json()
            idlist: list[str] = list(payload.get("esearchresult", {}).get("idlist") or [])
            total_count = int(payload.get("esearchresult", {}).get("count") or 0)
        except (ValueError, KeyError, TypeError) as exc:
            return [], FetchOutcome(status="parse_error", error=f"malformed ESearch JSON: {exc}")

        retstart = len(idlist)
        while idlist and len(idlist) < max_results and retstart < total_count:
            next_outcome = _esearch(
                client, query, since=since, retstart=retstart, retmax=min(page_size, max_results - len(idlist))
            )
            if next_outcome.status != "success":
                break
            try:
                next_payload = next_outcome.response.json()
                next_ids = list(next_payload.get("esearchresult", {}).get("idlist") or [])
            except (ValueError, KeyError, TypeError):
                break
            if not next_ids:
                break
            idlist.extend(next_ids)
            retstart += len(next_ids)

        idlist = idlist[:max_results]
        if not idlist:
            return [], FetchOutcome(status="success", attempts=search_outcome.attempts)

        fetch_outcome = _efetch(client, idlist)
        if fetch_outcome.status != "success":
            return [], fetch_outcome

        try:
            root = ElementTree.fromstring(fetch_outcome.response.text)
        except ElementTree.ParseError as exc:
            return [], FetchOutcome(status="parse_error", error=f"malformed EFetch XML: {exc}")

        papers = []
        for article_elem in root.findall("./PubmedArticle"):
            parsed = _parse_pubmed_article(article_elem)
            if parsed:
                papers.append(parsed)
        return papers, FetchOutcome(status="success", attempts=fetch_outcome.attempts)
