"""Loads the hardcoded known-cases JSON fixture into Document /
ApprovedIndication objects. Used by tests and by a manual demo script to
prove the scoring engine works before any real ingestion is wired up.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.schemas.document import ApprovedIndication, Document

KNOWN_CASES_PATH = Path(__file__).resolve().parents[2] / "data" / "known_cases.json"


def load_known_cases(
    path: Path = KNOWN_CASES_PATH,
) -> tuple[list[Document], list[ApprovedIndication]]:
    raw = json.loads(path.read_text())
    documents = [Document(**d) for d in raw["documents"]]
    approved = [ApprovedIndication(**a) for a in raw["approved_indications"]]
    return documents, approved
