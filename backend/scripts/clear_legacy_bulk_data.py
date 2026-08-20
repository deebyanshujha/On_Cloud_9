"""Clears legacy pre-discovery bulk-ingested documents (data-imbalance audit
fix, 2026-08-20).

**The problem this fixes.** Before Step 10 (dynamic discovery) existed, the
only way to get data in was `ingest_drug(drug)` called directly for a fixed
two-drug list (metformin, sildenafil), capped at 200 ClinicalTrials.gov
studies and 15 Europe PMC preprints *per drug*. Step 10's discovery mode
instead scans a shared `ARB_MAX_RESULTS_PER_SOURCE` budget (default 10)
across *whatever* drugs a broad, undirected query happens to surface in that
window, so any one dynamically-discovered drug only ever gets a thin slice.
The two legacy drugs' documents were never cleared out when discovery mode
shipped, so they still dwarf every other drug's count — not because they're
more heavily studied in reality (they may well be), but because they were
ingested under a completely different, much larger budget.

**How legacy rows are identified — structurally, not by a hardcoded date.**
The `known_drugs` table (`app/models/known_drug.py`) is *only* ever written
by discovery-mode ingestion (`app/ingestion/discovery.py` calling
`upsert_known_drug`) — a drug ingested via the old single-drug scripts was
never discovered, so it was never added there. So: normalize every
`documents.drug` value the same way discovery does
(`normalize_drug_name`, see `app/core/drug_normalization.py`) and check
whether that canonical name is in the `known_drugs` table. If it's not, that
document was never part of a fair discovery budget — it's legacy bulk data.
This holds regardless of when the script is run again in the future (no
hardcoded cutoff timestamp to keep in sync).

Usage (from backend/):
    py scripts/clear_legacy_bulk_data.py              # dry run (default)
    py scripts/clear_legacy_bulk_data.py --apply       # actually delete

On --apply: backs up the whole DB file (timestamped .bak) AND dumps the
exact deleted rows as JSON to backend/data/, before deleting anything.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.drug_normalization import normalize_drug_name
from app.models.db import DATA_DIR, SessionLocal, init_db
from app.models.document import DocumentRecord
from app.models.known_drug import KnownDrugRecord

DB_PATH = DATA_DIR / "arbitrage.db"


def find_legacy_document_ids(session) -> list[int]:
    """Returns ids of `documents` rows whose (normalized) drug was never
    seen by discovery-mode ingestion (i.e. has no `known_drugs` row)."""
    known_canonical_names = {
        row[0] for row in session.execute(select(KnownDrugRecord.canonical_name))
    }
    legacy_ids = []
    for doc_id, drug in session.execute(select(DocumentRecord.id, DocumentRecord.drug)):
        if normalize_drug_name(drug) not in known_canonical_names:
            legacy_ids.append(doc_id)
    return legacy_ids


def per_drug_counts(session) -> Counter:
    counts = Counter()
    for (drug,) in session.execute(select(DocumentRecord.drug)):
        counts[drug] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the legacy rows (default is a dry run that only prints what would happen).",
    )
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    try:
        before_counts = per_drug_counts(session)
        legacy_ids = find_legacy_document_ids(session)

        if not legacy_ids:
            print("No legacy (pre-discovery) documents found — nothing to do.")
            return

        legacy_rows = session.execute(
            select(DocumentRecord).where(DocumentRecord.id.in_(legacy_ids))
        ).scalars().all()
        legacy_drug_counts = Counter(r.drug for r in legacy_rows)

        print(f"{'[DRY RUN] ' if not args.apply else ''}Legacy (pre-discovery) documents found: {len(legacy_ids)}")
        for drug, count in legacy_drug_counts.most_common():
            print(f"  {drug}: {count}")

        if not args.apply:
            print("\nRe-run with --apply to actually delete these rows (a DB backup and a JSON dump of the deleted rows are made first).")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        backup_db_path = DB_PATH.with_name(f"arbitrage.db.{timestamp}.bak")
        shutil.copy2(DB_PATH, backup_db_path)
        print(f"\nDB file backed up to: {backup_db_path}")

        dump_path = DATA_DIR / f"legacy_documents_backup_{timestamp}.json"
        dump_path.write_text(
            json.dumps(
                [
                    {
                        "id": r.id,
                        "drug": r.drug,
                        "disease": r.disease,
                        "source": r.source,
                        "source_id": r.source_id,
                        "phase": r.phase,
                        "date": r.date.isoformat() if r.date else None,
                        "url": r.url,
                        "num_mentions": r.num_mentions,
                        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                    }
                    for r in legacy_rows
                ],
                indent=2,
            )
        )
        print(f"Deleted rows dumped to: {dump_path}")

        for r in legacy_rows:
            session.delete(r)
        session.commit()

        after_counts = per_drug_counts(session)

        print("\nBefore -> after per-drug document counts (drugs that changed):")
        for drug in sorted(set(before_counts) | set(after_counts)):
            b, a = before_counts.get(drug, 0), after_counts.get(drug, 0)
            if b != a:
                print(f"  {drug}: {b} -> {a}")

        print(f"\nTotal documents: {sum(before_counts.values())} -> {sum(after_counts.values())}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
