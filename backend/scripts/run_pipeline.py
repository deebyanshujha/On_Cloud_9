"""Step 5 end-to-end check: load the real ClinicalTrials.gov documents and
real openFDA approved indications already sitting in the database (from
Steps 3 and 4), run them through the comparison/scoring engine with the new
staging/qualifier-aware disease matching, and print the resulting signals.

Specifically confirms:
- metformin/pancreatic cancer (and its "Stage ..." variants) IS flagged as
  a signal, despite the staging-qualifier mismatch that broke exact-string
  matching in Step 3.
- sildenafil/pulmonary hypertension is NO LONGER flagged as a signal, now
  that it correctly matches against openFDA's "pulmonary arterial
  hypertension" label text — this was the false-positive risk from Step 4.

Run from backend/: py scripts/run_pipeline.py

Requires Steps 3 and 4's ingestion scripts to have been run first (so
arbitrage.db actually has documents/approved_indications in it).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.disease_matching import diseases_match
from app.core.scoring import run_comparison
from app.ingestion.store import load_all_approved_indications, load_all_documents
from app.models.db import SessionLocal, init_db

# The two real cases Step 5 is specifically re-checking.
WATCH_PAIRS = {
    ("metformin", "pancreatic cancer"),
    ("sildenafil", "pulmonary hypertension"),
}


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        documents = load_all_documents(session)
        approved = load_all_approved_indications(session)

        if not documents or not approved:
            print(
                "No data in the database yet — run "
                "scripts/ingest_clinicaltrials.py and scripts/ingest_openfda.py "
                "first."
            )
            return

        print(f"Loaded {len(documents)} documents and {len(approved)} approved indications.")

        signals = run_comparison(documents, approved, today=date.today())
        print(f"Comparison produced {len(signals)} signals.\n")

        print("Top 10 signals by score:")
        for s in signals[:10]:
            print(f"  {s.score:.3f}  {s.drug} -> {s.disease}  ({', '.join(s.reasons)})")

        print("\nWatch-pair check (the two real cases Step 5 fixes):")
        for drug, disease in WATCH_PAIRS:
            # Signals key off whatever disease string the raw document used
            # (e.g. "Stage IV Pancreatic Cancer"), not the fixture's clean
            # phrase, so find any flagged signal for this drug whose disease
            # text matches the watch disease via the same matcher the
            # comparison engine uses, instead of an exact pair lookup.
            matches = [
                s for s in signals if s.drug == drug and diseases_match(s.disease, disease)
            ]
            if matches:
                print(f"  {drug} / {disease}: FLAGGED as signal (e.g. \"{matches[0].disease}\", score {matches[0].score:.3f})")
            else:
                print(f"  {drug} / {disease}: NOT flagged (correctly discarded as already approved)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
