"""SQLAlchemy table for storing normalized {drug, disease, source, date, url}
records (see shared/schema.md). This is Step 3's storage target — the
comparison engine (app/core/scoring.py) doesn't know this table exists; it
only ever sees app.schemas.document.Document objects. A future step reads
rows out of this table and hands them to the engine as Document objects.
"""
from __future__ import annotations

from datetime import date as date_, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_id", "drug", "disease", name="uq_document_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drug: Mapped[str] = mapped_column(String, index=True)
    disease: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    num_mentions: Mapped[int] = mapped_column(Integer, default=1)
    evidence_type: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
