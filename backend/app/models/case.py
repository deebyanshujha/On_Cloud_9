"""SQLAlchemy tables for TheraLens Cases. Per the brief: model everything as
relational tables/join tables in the existing SQLite database — no graph
database. A Case has many comorbidity conditions and many current
medications (both free-text, dynamic — no hardcoded disease/drug lists), and
zero or more stored analysis runs (CaseAnalysisRecord holds the most recent
one as a JSON blob of the full reasoning trail, so GET /cases/{id} doesn't
need to recompute anything).
"""
from __future__ import annotations

from datetime import date as date_, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class CaseRecord(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    primary_condition: Mapped[str] = mapped_column(String, index=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Richer patient-context scalar fields (additive, all nullable — see
    # app/models/db.py's _migrate_add_missing_columns for how these get
    # ALTER-TABLE'd onto the existing `cases` table without touching
    # already-stored rows). Free-text, no hardcoded value lists, same
    # philosophy as primary_condition/comorbidities/current_medications.
    age_group: Mapped[str | None] = mapped_column(String, nullable=True)
    sex: Mapped[str | None] = mapped_column(String, nullable=True)
    disease_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    disease_subtype: Mapped[str | None] = mapped_column(String, nullable=True)
    disease_duration: Mapped[str | None] = mapped_column(String, nullable=True)


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


class CasePhenotypeRecord(Base):
    """A clinical characteristic/phenotype attached to a case. Free-text,
    one row per phenotype — same shape as CaseConditionRecord, since
    phenotypes are disease-like free text that will need the same kind of
    matching against retrieved evidence."""

    __tablename__ = "case_phenotypes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String)


class CasePreviousTreatmentRecord(Base):
    """A previous treatment attached to a case, with an optional recorded
    response (e.g. "no response", "partial", "relapsed"). Free-text,
    dynamic — no hardcoded drug/response list."""

    __tablename__ = "case_previous_treatments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    response: Mapped[str | None] = mapped_column(String, nullable=True)


class CaseBiomarkerRecord(Base):
    """A biomarker/lab result attached to a case, with an optional value
    (e.g. name="HER2", value="positive"). Free-text, dynamic."""

    __tablename__ = "case_biomarkers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    value: Mapped[str | None] = mapped_column(String, nullable=True)


class CaseGeneticMarkerRecord(Base):
    """A genetic/pharmacogenomic finding attached to a case (e.g.
    gene="BRCA1", variant="c.68_69delAG"). Free-text, dynamic."""

    __tablename__ = "case_genetic_markers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    gene: Mapped[str] = mapped_column(String)
    variant: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class CaseResearchEvidenceRecord(Base):
    """Case-specific runtime research cache.

    These rows are not global discovery documents. They preserve exactly
    what a case research run retrieved for a generated query, including the
    normalized entities and extracted relationship decisions, so a later
    refresh can compare against the prior case evidence without polluting
    the global signal corpus.
    """

    __tablename__ = "case_research_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    query: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    normalized_drugs: Mapped[str] = mapped_column(Text, default="[]")
    normalized_diseases: Mapped[str] = mapped_column(Text, default="[]")
    relationships_json: Mapped[str] = mapped_column(Text, default="[]")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
