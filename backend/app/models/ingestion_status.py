"""SQLAlchemy table tracking the last outcome of each source's discovery
run (Step 10 — fallback behavior). One row per source, overwritten each
run: lets the API/UI show a clear "source unavailable" indicator instead of
silently serving stale/cached data as if it were a complete live result.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class IngestionStatusRecord(Base):
    __tablename__ = "ingestion_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String)  # "ok" | "error"
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    items_ingested: Mapped[int] = mapped_column(Integer, default=0)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
