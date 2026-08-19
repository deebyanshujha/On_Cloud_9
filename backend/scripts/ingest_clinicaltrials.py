"""Step 3 sanity-check script: pull real ClinicalTrials.gov data for a
handful of drugs, store it in the database, and print a summary — including
whether the diseases we already know about from Step 2's hardcoded fixture
(pancreatic cancer for metformin, pulmonary hypertension for sildenafil)
actually show up in the real data.

Run from backend/: py scripts/ingest_clinicaltrials.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.clinicaltrials import ingest_drug
from app.ingestion.store import upsert_documents
from app.models.db import SessionLocal, init_db

DRUGS_TO_INGEST = ["metformin", "sildenafil"]

KNOWN_DISEASES_TO_LOOK_FOR = {
    "metformin": "pancreatic cancer",
    "sildenafil": "pulmonary hypertension",
}


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        for drug in DRUGS_TO_INGEST:
            print(f"Fetching ClinicalTrials.gov studies for '{drug}'...")
            documents = ingest_drug(drug, max_studies=200)
            print(f"  Parsed {len(documents)} drug-disease documents.")

            inserted, skipped = upsert_documents(session, documents)
            print(f"  Stored: {inserted} new, {skipped} already in DB (skipped).")

            diseases_seen = {d.normalized_disease() for d in documents}
            target = KNOWN_DISEASES_TO_LOOK_FOR.get(drug)
            if target:
                found = target in diseases_seen
                marker = "FOUND" if found else "not found"
                print(f"  Sanity check: '{target}' in real data -> {marker}")
            print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
