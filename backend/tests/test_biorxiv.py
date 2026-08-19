"""Tests for bioRxiv/medRxiv ingestion + NER extraction (Step 6). These use
a hand-crafted sample of the raw Europe PMC API shape and a lightweight
fake NER model, so they don't depend on network access, Europe PMC's live
data, or the real (120MB) scispaCy model being installed.
"""
from datetime import date

from app.ingestion.biorxiv import (
    extract_diseases,
    parse_preprint_to_documents,
    parse_publication_date,
    strip_html,
)


class _FakeEntity:
    def __init__(self, text: str, label: str):
        self.text = text
        self.label_ = label


class _FakeDoc:
    def __init__(self, ents: list[_FakeEntity]):
        self.ents = ents


class FakeNerModel:
    """Deterministic stand-in for the real scispaCy pipeline: returns
    whatever entities were registered for a given input text, so tests
    don't need the real 120MB model installed."""

    def __init__(self, entities_by_text: dict[str, list[_FakeEntity]]):
        self._entities_by_text = entities_by_text

    def __call__(self, text: str) -> _FakeDoc:
        return _FakeDoc(self._entities_by_text.get(text, []))


SAMPLE_PAPER = {
    "doi": "10.1101/2025.01.01.000001",
    "title": "Metformin reduces tumor growth in a mouse model",
    "abstractText": (
        "<h4>Background</h4> Metformin has shown activity against "
        "pancreatic cancer in preclinical models. <h4>Methods</h4> We "
        "tested metformin in a mouse xenograft model."
    ),
    "firstPublicationDate": "2025-01-15",
    "bookOrReportDetails": {"publisher": "bioRxiv"},
}

MEDRXIV_PAPER = {
    "doi": "10.1101/2025.02.02.000002",
    "title": "Sildenafil for pulmonary arterial hypertension: a trial",
    "abstractText": "Sildenafil improved outcomes in pulmonary arterial hypertension.",
    "firstPublicationDate": "2025-02-20",
    "bookOrReportDetails": {"publisher": "medRxiv"},
}


def test_strip_html_removes_tags_and_collapses_whitespace():
    assert (
        strip_html("<h4>Background</h4>  Some   text.  <h4>Methods</h4> More.")
        == "Background Some text. Methods More."
    )


def test_parse_publication_date_valid():
    assert parse_publication_date("2025-01-15") == date(2025, 1, 15)


def test_parse_publication_date_none_and_malformed():
    assert parse_publication_date(None) is None
    assert parse_publication_date("not-a-date") is None


def test_extract_diseases_filters_to_disease_label_and_dedupes():
    text = "some text"
    nlp = FakeNerModel(
        {
            text: [
                _FakeEntity("Pancreatic Cancer", "DISEASE"),
                _FakeEntity("Metformin", "CHEMICAL"),
                _FakeEntity("pancreatic cancer", "DISEASE"),  # duplicate, different case
                _FakeEntity("Diabetes", "DISEASE"),
            ]
        }
    )
    assert extract_diseases(nlp, text) == ["pancreatic cancer", "diabetes"]


def test_extract_diseases_no_disease_entities():
    text = "some text"
    nlp = FakeNerModel({text: [_FakeEntity("Metformin", "CHEMICAL")]})
    assert extract_diseases(nlp, text) == []


def test_parse_preprint_to_documents_basic_fields():
    doc_text = (
        "Metformin reduces tumor growth in a mouse model. "
        "Background Metformin has shown activity against pancreatic "
        "cancer in preclinical models. Methods We tested metformin in a "
        "mouse xenograft model."
    )
    nlp = FakeNerModel({doc_text: [_FakeEntity("pancreatic cancer", "DISEASE")]})

    docs = parse_preprint_to_documents(SAMPLE_PAPER, queried_drug="metformin", nlp=nlp)

    assert len(docs) == 1
    doc = docs[0]
    assert doc.drug == "metformin"
    assert doc.disease == "pancreatic cancer"
    assert doc.source == "biorxiv"
    assert doc.source_id == "10.1101/2025.01.01.000001"
    assert doc.phase is None
    assert doc.date == date(2025, 1, 15)
    assert doc.url == "https://doi.org/10.1101/2025.01.01.000001"


def test_parse_preprint_to_documents_medrxiv_publisher_maps_to_medrxiv_source():
    doc_text = (
        "Sildenafil for pulmonary arterial hypertension: a trial. "
        "Sildenafil improved outcomes in pulmonary arterial hypertension."
    )
    nlp = FakeNerModel(
        {doc_text: [_FakeEntity("pulmonary arterial hypertension", "DISEASE")]}
    )

    docs = parse_preprint_to_documents(MEDRXIV_PAPER, queried_drug="sildenafil", nlp=nlp)

    assert len(docs) == 1
    assert docs[0].source == "medrxiv"
    assert docs[0].disease == "pulmonary arterial hypertension"


def test_parse_preprint_to_documents_one_per_unique_disease():
    doc_text = "Title. Abstract."
    nlp = FakeNerModel(
        {
            doc_text: [
                _FakeEntity("pancreatic cancer", "DISEASE"),
                _FakeEntity("type 2 diabetes", "DISEASE"),
            ]
        }
    )
    paper = {**SAMPLE_PAPER, "title": "Title", "abstractText": "Abstract."}

    docs = parse_preprint_to_documents(paper, queried_drug="metformin", nlp=nlp)

    assert len(docs) == 2
    assert {d.disease for d in docs} == {"pancreatic cancer", "type 2 diabetes"}


def test_parse_preprint_to_documents_missing_doi_returns_empty():
    broken_paper = {**SAMPLE_PAPER}
    del broken_paper["doi"]
    nlp = FakeNerModel({})
    assert parse_preprint_to_documents(broken_paper, queried_drug="metformin", nlp=nlp) == []


def test_parse_preprint_to_documents_unrecognized_publisher_returns_empty():
    other_paper = {**SAMPLE_PAPER, "bookOrReportDetails": {"publisher": "Research Square"}}
    nlp = FakeNerModel({})
    assert parse_preprint_to_documents(other_paper, queried_drug="metformin", nlp=nlp) == []


def test_parse_preprint_to_documents_no_disease_entities_returns_empty():
    doc_text = "Title. Abstract."
    nlp = FakeNerModel({doc_text: [_FakeEntity("Metformin", "CHEMICAL")]})
    paper = {**SAMPLE_PAPER, "title": "Title", "abstractText": "Abstract."}
    assert parse_preprint_to_documents(paper, queried_drug="metformin", nlp=nlp) == []
