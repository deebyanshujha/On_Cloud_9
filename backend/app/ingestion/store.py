"""Saves normalized Document and ApprovedIndication objects into the
database, skipping ones already stored (matched on
source + source_id + drug + disease) so re-running ingestion doesn't create
duplicates.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.approved_indication import ApprovedIndicationRecord
from app.models.document import DocumentRecord
from app.schemas.document import ApprovedIndication, Document


def upsert_documents(session: Session, documents: list[Document]) -> tuple[int, int]:
    """Returns (num_inserted, num_skipped_as_duplicate)."""
    inserted = 0
    skipped = 0

    for doc in documents:
        exists = session.execute(
            select(DocumentRecord.id).where(
                DocumentRecord.source == doc.source,
                DocumentRecord.source_id == doc.source_id,
                DocumentRecord.drug == doc.normalized_drug(),
                DocumentRecord.disease == doc.normalized_disease(),
            )
        ).first()
        if exists:
            skipped += 1
            continue

        session.add(
            DocumentRecord(
                drug=doc.normalized_drug(),
                disease=doc.normalized_disease(),
                source=doc.source,
                source_id=doc.source_id,
                phase=doc.phase,
                date=doc.date,
                url=doc.url,
                num_mentions=doc.num_mentions,
            )
        )
        inserted += 1

    session.commit()
    return inserted, skipped


def load_all_documents(session: Session) -> list[Document]:
    records = session.execute(select(DocumentRecord)).scalars().all()
    return [
        Document(
            drug=r.drug,
            disease=r.disease,
            source=r.source,
            source_id=r.source_id,
            phase=r.phase,
            date=r.date,
            url=r.url,
            num_mentions=r.num_mentions,
        )
        for r in records
    ]


def upsert_approved_indications(
    session: Session, indications: list[ApprovedIndication]
) -> tuple[int, int]:
    """Same dedupe strategy as upsert_documents: matched on
    source + source_id + drug + disease so re-running ingestion doesn't
    create duplicates. Returns (num_inserted, num_skipped_as_duplicate)."""
    inserted = 0
    skipped = 0

    for indication in indications:
        exists = session.execute(
            select(ApprovedIndicationRecord.id).where(
                ApprovedIndicationRecord.source == indication.source,
                ApprovedIndicationRecord.source_id == indication.source_id,
                ApprovedIndicationRecord.drug == indication.normalized_drug(),
                ApprovedIndicationRecord.disease == indication.normalized_disease(),
            )
        ).first()
        if exists:
            skipped += 1
            continue

        session.add(
            ApprovedIndicationRecord(
                drug=indication.normalized_drug(),
                disease=indication.normalized_disease(),
                source=indication.source,
                source_id=indication.source_id,
                url=indication.url,
            )
        )
        inserted += 1

    session.commit()
    return inserted, skipped


def load_all_approved_indications(session: Session) -> list[ApprovedIndication]:
    records = session.execute(select(ApprovedIndicationRecord)).scalars().all()
    return [
        ApprovedIndication(
            drug=r.drug,
            disease=r.disease,
            source=r.source,
            source_id=r.source_id,
            url=r.url,
        )
        for r in records
    ]
