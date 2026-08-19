"""Discovery orchestration (Step 10) — the replacement for the old
"hardcoded 2-drug list drives everything" pipeline.

Order of operations, every run:
  1. ClinicalTrials.gov: scan recent studies broadly (no drug filter),
     extract every (drug, condition) pair, store as Documents, merge every
     drug name into the persistent known-drugs cache.
  2. Europe PMC (bioRxiv/medRxiv): same shift — scan recent preprints
     broadly, run NER for both drug (CHEMICAL) and disease (DISEASE)
     entities, store as Documents, merge drug names into the cache.
  3. openFDA: reactively look up approved indications for every drug
     discovered in steps 1-2 of *this run* (not the whole historical
     cache, to avoid re-hitting openFDA for drugs already looked up).

Each source is wrapped so a failure there is recorded and surfaced (via
`record_source_status`/`/status`) rather than silently swallowed — see
PROGRESS.md's "fallback behavior" section.
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.core.config import MAX_RESULTS_PER_SOURCE
from app.ingestion import biorxiv, clinicaltrials, openfda
from app.ingestion.store import (
    record_source_status,
    upsert_approved_indications,
    upsert_documents,
    upsert_known_drug,
)


def run_discovery(session: Session, max_results: int = MAX_RESULTS_PER_SOURCE) -> dict:
    """Runs the full discovery-driven ingestion pass and returns a summary
    dict (documents/drugs/approved-indications counts + per-source status),
    also used by scripts/run_pipeline.py for its printed report."""
    summary: dict = {"sources": {}}
    discovered_drugs: set[str] = set()

    # --- ClinicalTrials.gov ---
    try:
        documents = clinicaltrials.discover(max_studies=max_results)
        inserted, skipped = upsert_documents(session, documents)
        for doc in documents:
            discovered_drugs.add(upsert_known_drug(session, doc.drug))
        record_source_status(
            session, "clinicaltrials", "ok", items_ingested=inserted
        )
        summary["sources"]["clinicaltrials"] = {
            "status": "ok",
            "documents_found": len(documents),
            "inserted": inserted,
            "skipped": skipped,
        }
    except httpx.HTTPError as exc:
        record_source_status(session, "clinicaltrials", "error", message=str(exc))
        summary["sources"]["clinicaltrials"] = {"status": "error", "message": str(exc)}

    # --- Europe PMC (bioRxiv/medRxiv) ---
    try:
        documents = biorxiv.discover(max_results=max_results)
        inserted, skipped = upsert_documents(session, documents)
        for doc in documents:
            discovered_drugs.add(upsert_known_drug(session, doc.drug))
        record_source_status(session, "europepmc", "ok", items_ingested=inserted)
        summary["sources"]["europepmc"] = {
            "status": "ok",
            "documents_found": len(documents),
            "inserted": inserted,
            "skipped": skipped,
        }
    except httpx.HTTPError as exc:
        record_source_status(session, "europepmc", "error", message=str(exc))
        summary["sources"]["europepmc"] = {"status": "error", "message": str(exc)}
    except RuntimeError as exc:
        # load_ner_model() raises RuntimeError if the scispaCy model isn't
        # installed — a config/environment problem, not a source outage,
        # but still something the caller must not treat as "zero signals
        # found here, business as usual."
        record_source_status(session, "europepmc", "error", message=str(exc))
        summary["sources"]["europepmc"] = {"status": "error", "message": str(exc)}

    # --- openFDA (reactive: one lookup per drug discovered above) ---
    total_indications_inserted = 0
    openfda_errors: list[str] = []
    for drug in sorted(discovered_drugs):
        if not drug:
            continue
        try:
            indications = openfda.ingest_drug(drug)
            inserted, _skipped = upsert_approved_indications(session, indications)
            total_indications_inserted += inserted
        except httpx.HTTPError as exc:
            openfda_errors.append(f"{drug}: {exc}")

    if openfda_errors:
        record_source_status(
            session,
            "openfda",
            "error",
            message="; ".join(openfda_errors[:5]),
            items_ingested=total_indications_inserted,
        )
        summary["sources"]["openfda"] = {
            "status": "error",
            "errors": openfda_errors,
            "inserted": total_indications_inserted,
        }
    else:
        record_source_status(
            session, "openfda", "ok", items_ingested=total_indications_inserted
        )
        summary["sources"]["openfda"] = {
            "status": "ok",
            "drugs_looked_up": len(discovered_drugs),
            "inserted": total_indications_inserted,
        }

    summary["discovered_drugs"] = sorted(discovered_drugs)
    return summary
