"""Tests for openFDA Drug Label parsing logic (Step 4). These use a
hand-crafted sample of the raw API shape so they don't depend on network
access or on openFDA's live data.
"""
from app.ingestion.openfda import parse_label_to_indication

SAMPLE_LABEL = {
    "id": "8c26dc1a-fba3-4266-bfaf-624b0941ef8b",
    "set_id": "0098dec4-f0e5-45d5-8aa4-5d0faf9ab142",
    "indications_and_usage": [
        "INDICATIONS AND USAGE Metformin hydrochloride tablets are indicated "
        "as an adjunct to diet and exercise to improve glycemic control in "
        "adults with type 2 diabetes mellitus."
    ],
    "openfda": {"generic_name": ["METFORMIN HYDROCHLORIDE"]},
}

MULTI_PARAGRAPH_LABEL = {
    "id": "abc123",
    "indications_and_usage": [
        "First paragraph about diabetes.",
        "Second paragraph about something else.",
    ],
}


def test_parse_label_to_indication_basic_fields():
    indication = parse_label_to_indication(SAMPLE_LABEL, queried_drug="metformin")

    assert indication is not None
    assert indication.drug == "metformin"
    assert "type 2 diabetes mellitus" in indication.disease
    assert indication.source == "openfda"
    assert indication.source_id == "8c26dc1a-fba3-4266-bfaf-624b0941ef8b"
    assert "id:%228c26dc1a-fba3-4266-bfaf-624b0941ef8b%22" in indication.url


def test_parse_label_to_indication_joins_multiple_paragraphs():
    indication = parse_label_to_indication(MULTI_PARAGRAPH_LABEL, queried_drug="x")

    assert indication is not None
    assert "First paragraph" in indication.disease
    assert "Second paragraph" in indication.disease


def test_parse_label_to_indication_missing_id_returns_none():
    broken_label = {"indications_and_usage": ["some text"]}
    assert parse_label_to_indication(broken_label, queried_drug="metformin") is None


def test_parse_label_to_indication_missing_indications_returns_none():
    broken_label = {"id": "xyz", "indications_and_usage": []}
    assert parse_label_to_indication(broken_label, queried_drug="metformin") is None


def test_parse_label_to_indication_missing_field_entirely_returns_none():
    broken_label = {"id": "xyz"}
    assert parse_label_to_indication(broken_label, queried_drug="metformin") is None
