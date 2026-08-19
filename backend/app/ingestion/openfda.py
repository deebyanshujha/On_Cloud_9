"""openFDA Drug Label ingestion (Step 4) — ground truth for what a drug is
*already* FDA-approved to treat, so the comparison engine (Step 5+) can tell
"already approved" apart from "new pairing worth flagging."

Each openFDA label result carries one `indications_and_usage` field: a
free-text paragraph (not a clean list of disease names) describing what the
labeled product is indicated for. Splitting that paragraph into individual,
comparably-normalized disease names is the same class of problem as the
disease-name matching issue called out in app/ingestion/clinicaltrials.py's
docstring — deliberately deferred to Step 5. For now we store the raw
paragraph as the `disease` field of one ApprovedIndication per label; Step 5
decides how to search/match against it (substring, fuzzy, stripped
qualifiers, etc.).

No API key needed for the query volumes this project uses.
Docs: https://open.fda.gov/apis/drug/label/
"""
from __future__ import annotations

from typing import Iterator

import httpx

from app.core.config import OPENFDA_LABELS_PER_DRUG
from app.schemas.document import ApprovedIndication

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"


def fetch_raw_labels(drug: str, limit: int = OPENFDA_LABELS_PER_DRUG) -> Iterator[dict]:
    """Yields raw label dicts from the openFDA Drug Label API for a given
    generic drug name. openFDA caps `limit` at 100 per request; the small
    default here is plenty for ground-truth purposes."""
    params = {"search": f'openfda.generic_name:"{drug}"', "limit": limit}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(OPENFDA_LABEL_URL, params=params)
        if response.status_code == 404:
            # openFDA returns 404 (not an empty result set) when a search
            # matches nothing.
            return
        response.raise_for_status()
        payload = response.json()

    for label in payload.get("results", []):
        yield label


def _join_field(label: dict, *field_names: str) -> str | None:
    """Joins a free-text openFDA label field the same way
    indications_and_usage is joined: whichever of `field_names` is present
    first wins (openFDA labels sometimes use `warnings` and sometimes the
    newer `warnings_and_precautions` field for the same content), paragraphs
    are joined as-is, no fabrication/structuring. Returns None if the field
    is absent or empty, never an empty string."""
    for name in field_names:
        parts = label.get(name) or []
        text = " ".join(p.strip() for p in parts if p.strip())
        if text:
            return text
    return None


def parse_label_to_indication(
    label: dict, queried_drug: str
) -> ApprovedIndication | None:
    label_id = label.get("id")
    indications = label.get("indications_and_usage") or []
    if not label_id or not indications:
        return None

    # A label can (rarely) carry more than one indications_and_usage
    # paragraph; join them since they all describe the same labeled product.
    text = " ".join(part.strip() for part in indications if part.strip())
    if not text:
        return None

    return ApprovedIndication(
        drug=queried_drug,
        disease=text,
        source="openfda",
        source_id=label_id,
        url=f"{OPENFDA_LABEL_URL}?search=id:%22{label_id}%22",
        contraindications=_join_field(label, "contraindications"),
        warnings=_join_field(label, "warnings", "warnings_and_precautions"),
        drug_interactions=_join_field(label, "drug_interactions"),
    )


def ingest_drug(drug: str, limit: int = OPENFDA_LABELS_PER_DRUG) -> list[ApprovedIndication]:
    """Fetches and normalizes openFDA labels for one drug into
    ApprovedIndication objects. Does not touch the database — callers decide
    whether/how to store the result."""
    indications: list[ApprovedIndication] = []
    for label in fetch_raw_labels(drug, limit=limit):
        indication = parse_label_to_indication(label, queried_drug=drug)
        if indication is not None:
            indications.append(indication)
    return indications
