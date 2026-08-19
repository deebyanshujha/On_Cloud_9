"""Step 6 sanity-check script: pull a handful of real bioRxiv/medRxiv
preprint abstracts for metformin and sildenafil (via Europe PMC's search
index — see app/ingestion/biorxiv.py's docstring for why), run the local
scispaCy NER model over them to extract mentioned diseases, store the
results, and print a few real abstracts alongside what NER pulled out of
them so the extraction quality can be eyeballed directly.

Run from backend/: py scripts/ingest_biorxiv.py

Requires the scispaCy NER model to be installed first:
  pip install "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.biorxiv import fetch_raw_preprints, load_ner_model, parse_preprint_to_documents, strip_html
from app.ingestion.store import upsert_documents
from app.models.db import SessionLocal, init_db

DRUGS_TO_INGEST = ["metformin", "sildenafil"]
MAX_RESULTS_PER_DRUG = 15
NUM_ABSTRACTS_TO_PRINT = 3


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        print("Loading scispaCy NER model (en_ner_bc5cdr_md)...")
        nlp = load_ner_model()
        print("Loaded.\n")

        for drug in DRUGS_TO_INGEST:
            print(f"Fetching bioRxiv/medRxiv preprints mentioning '{drug}' (via Europe PMC)...")
            papers = list(fetch_raw_preprints(drug, max_results=MAX_RESULTS_PER_DRUG))
            print(f"  Found {len(papers)} preprint(s).")

            documents = []
            for paper in papers:
                documents.extend(parse_preprint_to_documents(paper, queried_drug=drug, nlp=nlp))
            print(f"  NER extracted {len(documents)} drug-disease documents.")

            inserted, skipped = upsert_documents(session, documents)
            print(f"  Stored: {inserted} new, {skipped} already in DB (skipped).")

            print(f"  Sample abstracts + extracted diseases (first {NUM_ABSTRACTS_TO_PRINT}):")
            for paper in papers[:NUM_ABSTRACTS_TO_PRINT]:
                title = paper.get("title", "")
                abstract = strip_html(paper.get("abstractText", ""))
                publisher = (paper.get("bookOrReportDetails") or {}).get("publisher", "?")
                diseases = sorted({
                    d.disease for d in parse_preprint_to_documents(paper, queried_drug=drug, nlp=nlp)
                })
                print(f"    [{publisher}] {title}")
                print(f"      abstract: {abstract[:300]}{'...' if len(abstract) > 300 else ''}")
                print(f"      NER-extracted diseases: {diseases if diseases else '(none found)'}")
                print()
            print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
