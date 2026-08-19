"""openFDA reactive-lookup sanity-check script (Step 10).

Unlike ClinicalTrials.gov/Europe PMC, openFDA genuinely needs a drug name
to look up its label — there's nothing to "discover" here. So this script
doesn't scan anything broadly: it looks up every drug already sitting in
the persistent known-drugs cache (populated by
scripts/ingest_clinicaltrials.py / scripts/ingest_biorxiv.py), one openFDA
label lookup per drug, reactively.

Run from backend/: py scripts/ingest_openfda.py
(requires the known-drugs cache to be non-empty — run the two discovery
scripts above at least once first)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.openfda import ingest_drug
from app.ingestion.store import load_all_known_drugs, upsert_approved_indications
from app.models.db import SessionLocal, init_db


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        drugs = load_all_known_drugs(session)
        if not drugs:
            print(
                "No drugs in the known-drugs cache yet — run "
                "scripts/ingest_clinicaltrials.py and/or scripts/ingest_biorxiv.py first."
            )
            return

        print(f"Looking up openFDA labels for {len(drugs)} known drug(s)...")
        for drug in drugs:
            indications = ingest_drug(drug)
            inserted, skipped = upsert_approved_indications(session, indications)
            print(
                f"  {drug}: {len(indications)} label(s) found "
                f"({inserted} new, {skipped} already in DB)"
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
