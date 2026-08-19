"""ClinicalTrials.gov discovery-mode sanity-check script (Step 10).

Scans recent ClinicalTrials.gov studies broadly (no drug filter — see
app/ingestion/clinicaltrials.py's `discover()`), extracts every
(drug, condition) pair found, stores them, and merges every discovered
drug name into the persistent known-drugs cache.

Scan size / time window are runtime-configurable via env vars
(ARB_MAX_RESULTS_PER_SOURCE, ARB_TIME_WINDOW_DAYS) — see app/core/config.py.

Run from backend/: py scripts/ingest_clinicaltrials.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import MAX_RESULTS_PER_SOURCE, TIME_WINDOW_DAYS
from app.ingestion.clinicaltrials import discover
from app.ingestion.store import upsert_documents, upsert_known_drug
from app.models.db import SessionLocal, init_db


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        print(
            f"Scanning ClinicalTrials.gov for studies posted in the last "
            f"{TIME_WINDOW_DAYS} days (up to {MAX_RESULTS_PER_SOURCE} studies)..."
        )
        documents = discover(max_studies=MAX_RESULTS_PER_SOURCE)
        print(f"  Parsed {len(documents)} drug-disease documents.")

        inserted, skipped = upsert_documents(session, documents)
        print(f"  Stored: {inserted} new, {skipped} already in DB (skipped).")

        discovered_drugs = sorted({upsert_known_drug(session, d.drug) for d in documents})
        print(f"  Discovered {len(discovered_drugs)} distinct drug(s): {discovered_drugs[:20]}"
              f"{'...' if len(discovered_drugs) > 20 else ''}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
