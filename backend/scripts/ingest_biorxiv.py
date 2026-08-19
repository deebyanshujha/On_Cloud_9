"""bioRxiv/medRxiv discovery-mode sanity-check script (Step 10).

Scans recent bioRxiv/medRxiv preprints broadly via Europe PMC (no drug
keyword — see app/ingestion/biorxiv.py's `discover()`), runs the local
scispaCy NER model over each abstract for both drug (CHEMICAL) and disease
(DISEASE) entities, stores every pair found, and merges every discovered
drug name into the persistent known-drugs cache.

Scan size / time window are runtime-configurable via env vars
(ARB_MAX_RESULTS_PER_SOURCE, ARB_TIME_WINDOW_DAYS) — see app/core/config.py.

Requires the scispaCy NER model to be installed first:
  pip install "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz"

Run from backend/: py scripts/ingest_biorxiv.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import MAX_RESULTS_PER_SOURCE, TIME_WINDOW_DAYS
from app.ingestion.biorxiv import discover, load_ner_model
from app.ingestion.store import upsert_documents, upsert_known_drug
from app.models.db import SessionLocal, init_db


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        print("Loading scispaCy NER model (en_ner_bc5cdr_md)...")
        nlp = load_ner_model()
        print("Loaded.\n")

        print(
            f"Scanning bioRxiv/medRxiv (via Europe PMC) for preprints published in "
            f"the last {TIME_WINDOW_DAYS} days (up to {MAX_RESULTS_PER_SOURCE} preprints)..."
        )
        documents = discover(max_results=MAX_RESULTS_PER_SOURCE, nlp=nlp)
        print(f"  NER extracted {len(documents)} drug-disease documents.")

        inserted, skipped = upsert_documents(session, documents)
        print(f"  Stored: {inserted} new, {skipped} already in DB (skipped).")

        discovered_drugs = sorted({upsert_known_drug(session, d.drug) for d in documents})
        print(f"  Discovered {len(discovered_drugs)} distinct drug(s): {discovered_drugs[:20]}"
              f"{'...' if len(discovered_drugs) > 20 else ''}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
