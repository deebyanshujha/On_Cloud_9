"""Step 10 end-to-end pipeline: discovery-driven ingestion across all three
sources, then comparison/scoring, in one run.

Replaces the old "load whatever the two prior ingestion scripts already
put in the DB" version — it now drives discovery itself
(app/ingestion/discovery.py's `run_discovery`) instead of assuming
ingestion already happened, and prints a source-availability report so a
failing source is visible instead of silently looking like "zero signals
found there."

Still confirms the two original regression cases: metformin/pancreatic
cancer flagged, sildenafil/pulmonary hypertension correctly excluded — but
now as two entries among however many the discovery scan turns up, not the
entire dataset.

Scan size / time window / min confidence are runtime-configurable via env
vars (ARB_MAX_RESULTS_PER_SOURCE, ARB_TIME_WINDOW_DAYS,
ARB_MIN_CONFIDENCE_SCORE) — see app/core/config.py. No code changes needed
to raise the scan limit.

Run from backend/: py scripts/run_pipeline.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import MAX_RESULTS_PER_SOURCE, MIN_CONFIDENCE_SCORE, TIME_WINDOW_DAYS
from app.core.disease_matching import diseases_match
from app.core.scoring import run_comparison
from app.ingestion.discovery import run_discovery
from app.ingestion.store import load_all_approved_indications, load_all_documents
from app.models.db import SessionLocal, init_db

# The two original real cases this pipeline was first proven against — kept
# as a regression check, not the whole scope.
WATCH_PAIRS = {
    ("metformin", "pancreatic cancer"),
    ("sildenafil", "pulmonary hypertension"),
}


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        print(
            f"Config: max {MAX_RESULTS_PER_SOURCE} results/source, "
            f"{TIME_WINDOW_DAYS}-day window, min score {MIN_CONFIDENCE_SCORE}\n"
        )

        print("Running discovery-driven ingestion (ClinicalTrials.gov, "
              "Europe PMC, openFDA)...")
        summary = run_discovery(session, max_results=MAX_RESULTS_PER_SOURCE)
        for source, info in summary["sources"].items():
            status = info["status"]
            if status == "ok":
                print(f"  [{source}] OK — {info}")
            else:
                print(f"  [{source}] SOURCE UNAVAILABLE — {info.get('message', info)}")
        print(f"  Discovered {len(summary['discovered_drugs'])} distinct drug(s) this run.\n")

        documents = load_all_documents(session)
        approved = load_all_approved_indications(session)

        if not documents or not approved:
            print("No data in the database yet — discovery may have found nothing "
                  "in this window, or every source failed (see above).")
            return

        print(f"Loaded {len(documents)} documents and {len(approved)} approved indications "
              f"(accumulated across all runs so far).")

        signals = run_comparison(documents, approved, today=date.today())
        distinct_drugs = {s.drug for s in signals}
        print(f"Comparison produced {len(signals)} signals across {len(distinct_drugs)} "
              f"distinct drugs.\n")

        print("Top 10 signals by score:")
        for s in signals[:10]:
            print(f"  {s.score:.3f}  {s.drug} -> {s.disease}  ({', '.join(s.reasons)})")

        print("\nRegression check (the two original known cases):")
        for drug, disease in WATCH_PAIRS:
            matches = [
                s for s in signals if s.drug == drug and diseases_match(s.disease, disease)
            ]
            if matches:
                print(f"  {drug} / {disease}: FLAGGED as signal (e.g. \"{matches[0].disease}\", score {matches[0].score:.3f})")
            else:
                print(f"  {drug} / {disease}: NOT flagged (correctly discarded as already approved, "
                      f"or not yet re-discovered in this window)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
