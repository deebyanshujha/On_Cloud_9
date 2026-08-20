"""SQLAlchemy table for the persistent, growing "known drugs" cache (Step
10). Unlike `documents`/`approved_indications` (one row per observation),
this table has one row per *canonical drug entity* — every surface-form
variant discovered across runs (brand names, salt/dosage-form suffixes,
case differences) merges into the same row instead of creating a new one,
so the cache accumulates rather than resets on each pipeline run.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class KnownDrugRecord(Base):
    __tablename__ = "known_drugs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    # JSON-encoded list of raw surface forms seen (e.g. ["Metformin
    # Hydrochloride 500mg", "metformin"]) — kept for traceability/debugging,
    # not used for matching (matching always goes through canonical_name).
    name_variants: Mapped[str] = mapped_column(String, default="[]")
    rxnorm_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # "drug" | "drug_class" | "rejected" — see
    # app.core.drug_normalization.DRUG_CLASS_ALLOWLIST /
    # is_valid_medication_entity. Nullable (not NOT NULL): the sqlite
    # ADD-COLUMN migration in app/models/db.py can't backfill existing
    # rows, so historical rows predating this column have no value here —
    # treat null the same as "drug" when reading. New rows always get one
    # via upsert_known_drug's default="drug" argument.
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True, default="drug")
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
