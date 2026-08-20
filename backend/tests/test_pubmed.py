"""Tests for the PubMed E-utilities adapter (app/ingestion/pubmed.py) —
ESearch + EFetch, retry classification, and converting real PubMed XML
into the same paper-dict shape app/core/runtime_research.py already knows
how to parse for Europe PMC. No network: httpx.Client is monkeypatched to
a scripted fake so ESearch/EFetch responses are fully controlled.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.ingestion.pubmed as pubmed_module
from app.ingestion.pubmed import _parse_pubmed_article, search_pubmed
from xml.etree import ElementTree

SINCE = date.today() - timedelta(days=365)

ESEARCH_OK = '{"esearchresult": {"count": "2", "retmax": "2", "retstart": "0", "idlist": ["111", "222"]}}'
ESEARCH_EMPTY = '{"esearchresult": {"count": "0", "retmax": "0", "retstart": "0", "idlist": []}}'

EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111</PMID>
      <Article>
        <ArticleTitle>Metformin reduces heart failure risk in a cohort study</ArticleTitle>
        <Abstract>
          <AbstractText>Metformin was administered and evaluated for heart failure outcomes in this study.</AbstractText>
        </Abstract>
        <Journal><JournalIssue><PubDate><Year>2024</Year><Month>Mar</Month><Day>15</Day></PubDate></JournalIssue></Journal>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
        <ELocationID EIdType="doi">10.1234/example.111</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>222</PMID>
      <Article>
        <ArticleTitle>An unrelated preprint</ArticleTitle>
        <Abstract>
          <AbstractText>Some other abstract text.</AbstractText>
        </Abstract>
        <Journal><JournalIssue><PubDate><MedlineDate>2020 Jan-Feb</MedlineDate></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.headers: dict = {}

    def json(self):
        import json

        return json.loads(self.text)


class _ScriptedClient:
    def __init__(self, script: list):
        self.script = list(script)

    def get(self, url, params=None):
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_client(monkeypatch, script: list):
    monkeypatch.setattr(pubmed_module.httpx, "Client", lambda timeout=30.0: _ScriptedClient(script))


def test_search_pubmed_success_with_results(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, ESEARCH_OK), _FakeResponse(200, EFETCH_XML)])
    papers, outcome = search_pubmed("metformin heart failure", since=SINCE, page_size=10, max_results=10)
    assert outcome.status == "success"
    assert len(papers) == 2
    first = papers[0]
    assert first["pmid"] == "111"
    assert first["source"] == "MED"
    assert first["doi"] == "10.1234/example.111"
    assert "Metformin" in first["title"]
    assert "heart failure outcomes" in first["abstractText"]
    assert first["firstPublicationDate"] == "2024-03-15"
    assert "Randomized Controlled Trial" in first["pubTypeList"]["pubType"]
    # MedlineDate-only fallback still yields a year-level date, not a crash
    assert papers[1]["firstPublicationDate"] == "2020-01-01"


def test_search_pubmed_success_with_zero_results(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, ESEARCH_EMPTY)])
    papers, outcome = search_pubmed("nonsense query xyz", since=SINCE, page_size=10, max_results=10)
    assert outcome.status == "success"
    assert papers == []


def test_search_pubmed_esearch_timeout_is_classified_not_swallowed(monkeypatch):
    import httpx as httpx_module

    _patch_client(monkeypatch, [httpx_module.TimeoutException("slow")] * 10)
    papers, outcome = search_pubmed("query", since=SINCE, page_size=10, max_results=10)
    assert papers == []
    assert outcome.status == "timeout"


def test_search_pubmed_esearch_rate_limited(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(429, "")] * 10)
    papers, outcome = search_pubmed("query", since=SINCE, page_size=10, max_results=10)
    assert papers == []
    assert outcome.status == "rate_limited"


def test_search_pubmed_malformed_esearch_json_is_parse_error(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, "{not valid json")])
    papers, outcome = search_pubmed("query", since=SINCE, page_size=10, max_results=10)
    assert papers == []
    assert outcome.status == "parse_error"


def test_search_pubmed_malformed_efetch_xml_is_parse_error(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, ESEARCH_OK), _FakeResponse(200, "<not><valid xml")])
    papers, outcome = search_pubmed("query", since=SINCE, page_size=10, max_results=10)
    assert papers == []
    assert outcome.status == "parse_error"


def test_search_pubmed_efetch_http_error(monkeypatch):
    _patch_client(
        monkeypatch,
        [_FakeResponse(200, ESEARCH_OK)] + [_FakeResponse(500, "boom")] * 3,
    )
    papers, outcome = search_pubmed("query", since=SINCE, page_size=10, max_results=10)
    assert papers == []
    assert outcome.status == "http_error"


def test_parse_pubmed_article_maps_to_europepmc_compatible_shape():
    root = ElementTree.fromstring(EFETCH_XML)
    article = root.find("./PubmedArticle")
    parsed = _parse_pubmed_article(article)
    assert parsed["pmid"] == "111"
    # source="MED" is what makes _publication_source_and_id in
    # runtime_research.py resolve this to the "pubmed" source, exactly
    # like an Europe PMC record whose own `source` field is "MED" — this
    # is the mechanism that gives Europe PMC + PubMed automatic
    # cross-source dedup on shared PMIDs.
    assert parsed["source"] == "MED"
