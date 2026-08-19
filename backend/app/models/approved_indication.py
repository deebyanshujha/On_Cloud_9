"""SQLAlchemy table for storing normalized {drug, disease, source, url}
ground-truth records (see shared/schema.md). This is Step 4's storage
target, mirroring app/models/document.py: the comparison engine doesn't know
this table exists; it only ever sees app.schemas.document.ApprovedIndication
objects.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ApprovedIndicationRecord(Base):
    __tablename__ = "approved_indications"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_id", "drug", "disease", name="uq_approved_indication_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drug: Mapped[str] = mapped_column(String, index=True)
    disease: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
