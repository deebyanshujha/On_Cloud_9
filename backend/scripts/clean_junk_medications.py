"""Retroactively removes junk "medication" rows ingested before the
junk-drug-name reject list existed (TheraLens redesign Phase A, 2026-08-20).

**The problem this fixes.** `app/ingestion/clinicaltrials.py`'s
`extract_drug_names()` already filtered ClinicalTrials.gov interventions to
`type == "DRUG"` only — but CT.gov sponsors routinely tag placebo/comparator
arms, "Standard of Care", bare cohort/part labels, and even stray protocol
sentences as intervention type `"DRUG"` too (a real quirk of their taxonomy,
not a bug in that filter). Everything ingested before
`app.core.drug_normalization.is_junk_drug_name()` existed has none of that
filtering applied, so junk like "Placebo" or "Pemefolacianib Cohort 1 In
Part A" ended up stored as if it were a real medication.

**Deletion criterion — deliberately conservative.** Only
`is_junk_drug_name()` (a deterministic, no-network text check: exact
placebo/procedure/comparator matches, bare cohort/arm/part labels, or
protocol-sentence-length text) is used to decide what gets deleted. This
script does NOT delete purely on a failed `is_valid_medication_entity()` /
RxNorm lookup, even though that function exists — RxNorm not recognizing a
name is inherently ambiguous (many real trial-stage compounds, e.g.
"lezertinib"-style codenames, simply aren't in RxNorm yet, and a transient
network hiccup looks identical to "not found"). Deleting on that signal
risks purging real medications, which is worse than leaving a few
unresolved-but-real drug names in place. RxNorm resolution is instead
reported for visibility only (see the "unresolved, kept" note below) — not
used as a deletion trigger.

Usage (from backend/):
    py scripts/clean_junk_medications.py              # dry run (default)
    py scripts/clean_junk_medications.py --apply       # actually delete

On --apply: backs up the whole DB file (timestamped .bak) AND dumps the
exact deleted rows as JSON to backend/data/, before deleting anything —
same safety pattern as scripts/clear_legacy_bulk_data.py.
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

from app.core.drug_normalization import is_junk_drug_name, is_valid_medication_entity
from app.models.case import CaseMedicationRecord
from app.models.db import DATA_DIR, SessionLocal, init_db
from app.models.document import DocumentRecord
from app.models.known_drug import KnownDrugRecord

DB_PATH = DATA_DIR / "arbitrage.db"


def find_junk_document_ids(session) -> list[int]:
    return [
        doc_id
        for doc_id, drug in session.execute(select(DocumentRecord.id, DocumentRecord.drug))
        if is_junk_drug_name(drug)
    ]


def find_junk_known_drug_ids(session) -> list[int]:
    return [
        row_id
        for row_id, name in session.execute(
            select(KnownDrugRecord.id, KnownDrugRecord.canonical_name)
        )
        if is_junk_drug_name(name)
    ]


def find_junk_case_medication_ids(session) -> list[int]:
    return [
        row_id
        for row_id, name in session.execute(
            select(CaseMedicationRecord.id, CaseMedicationRecord.name)
        )
        if is_junk_drug_name(name)
    ]


def per_drug_document_counts(session) -> Counter:
    counts = Counter()
    for (drug,) in session.execute(select(DocumentRecord.drug)):
        counts[drug] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete the junk rows (default is a dry run that only prints what would happen).",
    )
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    try:
        before_counts = per_drug_document_counts(session)

        junk_doc_ids = find_junk_document_ids(session)
        junk_known_drug_ids = find_junk_known_drug_ids(session)
        junk_case_med_ids = find_junk_case_medication_ids(session)

        junk_docs = session.execute(
            select(DocumentRecord).where(DocumentRecord.id.in_(junk_doc_ids))
        ).scalars().all() if junk_doc_ids else []
        junk_known_drugs = session.execute(
            select(KnownDrugRecord).where(KnownDrugRecord.id.in_(junk_known_drug_ids))
        ).scalars().all() if junk_known_drug_ids else []
        junk_case_meds = session.execute(
            select(CaseMedicationRecord).where(CaseMedicationRecord.id.in_(junk_case_med_ids))
        ).scalars().all() if junk_case_med_ids else []

        tag = "[DRY RUN] " if not args.apply else ""
        print(f"{tag}Junk documents found: {len(junk_docs)}")
        for drug, count in Counter(r.drug for r in junk_docs).most_common(20):
            print(f"  {drug!r}: {count}")
        print(f"\n{tag}Junk known_drugs entries found: {len(junk_known_drugs)}")
        for r in junk_known_drugs:
            print(f"  {r.canonical_name!r}")
        print(f"\n{tag}Junk case_medications entries found: {len(junk_case_meds)}")
        for r in junk_case_meds:
            print(f"  {r.name!r}")

        # Visibility-only: which SURVIVING (non-junk) drugs don't resolve via
        # RxNorm. Not a deletion criterion — see module docstring — just
        # useful to see what a follow-up manual review might want to check.
        surviving_drugs = sorted(set(before_counts) - {r.drug for r in junk_docs})
        unresolved = [d for d in surviving_drugs if not is_valid_medication_entity(d)]
        if unresolved:
            print(
                f"\n(Informational only, not deleted) {len(unresolved)} surviving drug "
                f"name(s) didn't resolve via RxNorm — could be real trial-stage "
                f"compounds RxNorm doesn't have yet, or missed junk; worth a manual look:"
            )
            for d in unresolved[:20]:
                print(f"  {d!r}")
            if len(unresolved) > 20:
                print(f"  ... and {len(unresolved) - 20} more")

        if not (junk_docs or junk_known_drugs or junk_case_meds):
            print("\nNothing to do.")
            return

        if not args.apply:
            print("\nRe-run with --apply to actually delete these rows (a DB backup and a JSON dump of the deleted rows are made first).")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        backup_db_path = DB_PATH.with_name(f"arbitrage.db.{timestamp}.bak")
        shutil.copy2(DB_PATH, backup_db_path)
        print(f"\nDB file backed up to: {backup_db_path}")

        dump_path = DATA_DIR / f"junk_medications_backup_{timestamp}.json"
        dump_path.write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "id": r.id, "drug": r.drug, "disease": r.disease,
                            "source": r.source, "source_id": r.source_id,
                            "phase": r.phase, "date": r.date.isoformat() if r.date else None,
                            "url": r.url, "num_mentions": r.num_mentions,
                            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                        }
                        for r in junk_docs
                    ],
                    "known_drugs": [
                        {
                            "id": r.id, "canonical_name": r.canonical_name,
                            "name_variants": r.name_variants, "rxnorm_id": r.rxnorm_id,
                        }
                        for r in junk_known_drugs
                    ],
                    "case_medications": [
                        {"id": r.id, "case_id": r.case_id, "name": r.name}
                        for r in junk_case_meds
                    ],
                },
                indent=2,
            )
        )
        print(f"Deleted rows dumped to: {dump_path}")

        for r in junk_docs:
            session.delete(r)
        for r in junk_known_drugs:
            session.delete(r)
        for r in junk_case_meds:
            session.delete(r)
        session.commit()

        after_counts = per_drug_document_counts(session)
        remaining_drugs = sorted(after_counts)
        print(f"\nDocuments: {sum(before_counts.values())} -> {sum(after_counts.values())}")
        print(f"Distinct drugs remaining: {len(remaining_drugs)}")
        print("Sample of remaining medications:")
        for d in remaining_drugs[:15]:
            print(f"  {d!r}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
