"""SQLAlchemy tables for TheraLens Cases. Per the brief: model everything as
relational tables/join tables in the existing SQLite database — no graph
database. A Case has many comorbidity conditions and many current
medications (both free-text, dynamic — no hardcoded disease/drug lists), and
zero or more stored analysis runs (CaseAnalysisRecord holds the most recent
one as a JSON blob of the full reasoning trail, so GET /cases/{id} doesn't
need to recompute anything).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class CaseRecord(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    primary_condition: Mapped[str] = mapped_column(String, index=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CaseConditionRecord(Base):
    """A comorbidity attached to a case. Free-text, one row per condition."""

    __tablename__ = "case_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String)


class CaseMedicationRecord(Base):
    """A current medication attached to a case. Free-text, one row per
    medication."""

    __tablename__ = "case_medications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String)


class CaseAnalysisRecord(Base):
    """The most recent analyze-run result for a case, stored as JSON so
    GET /cases/{id} can return it without recomputing. Overwritten (not
    appended) on each new POST /cases/{id}/analyze — "last analysis result"
    per the brief, not a history table."""

    __tablename__ = "case_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), unique=True, index=True)
    result_json: Mapped[str] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CaseSnapshotRecord(Base):
    """Phase 3: the analysis result captured at the moment a case was
    saved (PATCH /cases/{id} with saved=true) — distinct from
    CaseAnalysisRecord's "last analysis," which gets overwritten by every
    subsequent analyze/re-check call. This is the fixed baseline that
    "Re-check for new evidence" diffs against. Overwritten each time the
    case is (re-)saved, not a history table."""

    __tablename__ = "case_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), unique=True, index=True)
    result_json: Mapped[str] = mapped_column(Text)
    snapshotted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CaseEvidenceCheckRecord(Base):
    """Phase 3: the result of the most recent manually-triggered "Re-check
    for new evidence" for a case — stored so the dashboard-level "N saved
    cases have new evidence" summary can read it without re-running the
    diff for every case on every page load. Overwritten each re-check, not
    a history table."""

    __tablename__ = "case_evidence_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), unique=True, index=True)
    has_new_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    result_json: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
