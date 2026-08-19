"""Step 4 sanity-check script: pull real openFDA Drug Label data for a
handful of drugs, store it in the database, and print each approved
indications paragraph so we can visually confirm the diseases Step 2's
hardcoded fixture flags as "new" (pancreatic cancer for metformin,
pulmonary hypertension for sildenafil) do NOT already show up as approved
uses — i.e. these really are candidate repurposing pairings, not
already-approved ones we'd be re-flagging by mistake.

This is a print-and-eyeball check, not a real matching algorithm — the
substring search below is a rough approximation. Real matching (handling
things like "Stage IV Pancreatic Cancer" vs "pancreatic cancer") is Step 5's
job, per app/ingestion/openfda.py's docstring.

Run from backend/: py scripts/ingest_openfda.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.openfda import ingest_drug
from app.ingestion.store import upsert_approved_indications
from app.models.db import SessionLocal, init_db

DRUGS_TO_INGEST = ["metformin", "sildenafil"]

# Diseases we do NOT expect to find in these drugs' approved indications —
# if one of these turns up, it means the drug is already approved for it,
# and it isn't the "surprising new pairing" Step 2's fixture claims it is.
UNEXPECTED_DISEASES_TO_CHECK = {
    "metformin": "pancreatic cancer",
    "sildenafil": "pulmonary hypertension",
}


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        for drug in DRUGS_TO_INGEST:
            print(f"Fetching openFDA labels for '{drug}'...")
            indications = ingest_drug(drug, limit=10)
            print(f"  Parsed {len(indications)} approved-indication label(s).")

            inserted, skipped = upsert_approved_indications(session, indications)
            print(f"  Stored: {inserted} new, {skipped} already in DB (skipped).")

            print("  Approved indications text (for visual review):")
            for indication in indications:
                print(f"    [{indication.source_id}] {indication.disease}")
                print()

            unexpected = UNEXPECTED_DISEASES_TO_CHECK.get(drug)
            if unexpected:
                combined_text = " ".join(i.normalized_disease() for i in indications)
                found = unexpected in combined_text
                marker = "FOUND (not a new pairing!)" if found else "not found (still a candidate)"
                print(f"  Sanity check: '{unexpected}' in approved text -> {marker}")
            print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
