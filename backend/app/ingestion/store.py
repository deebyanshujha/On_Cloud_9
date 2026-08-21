"""Saves normalized Document and ApprovedIndication objects into the
database, skipping ones already stored (matched on
source + source_id + drug + disease) so re-running ingestion doesn't create
duplicates.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.drug_normalization import (
    DRUG_CLASS_ALLOWLIST,
    is_junk_drug_name,
    normalize_drug_name,
    resolve_rxnorm_id,
)
from app.core.scoring import normalize as normalize_disease_text
from app.models.approved_indication import ApprovedIndicationRecord
from app.models.case import (
    CaseAnalysisRecord,
    CaseBiomarkerRecord,
    CaseConditionRecord,
    CaseEvidenceCheckRecord,
    CaseGeneticMarkerRecord,
    CaseMedicationRecord,
    CasePhenotypeRecord,
    CasePreviousTreatmentRecord,
    CaseResearchEvidenceRecord,
    CaseRecord,
    CaseSnapshotRecord,
)
from app.models.document import DocumentRecord
from app.models.ingestion_status import IngestionStatusRecord
from app.models.known_drug import KnownDrugRecord
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
                evidence_type=doc.evidence_type,
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
            evidence_type=r.evidence_type,
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
                contraindications=indication.contraindications,
                warnings=indication.warnings,
                drug_interactions=indication.drug_interactions,
            )
        )
        inserted += 1

    session.commit()
    return inserted, skipped


def upsert_known_drug(
    session: Session, raw_name: str, resolve_rxnorm: bool = True
) -> str:
    """Merges a raw discovered drug/intervention name into the persistent
    known-drugs cache: same canonical name -> same row (variant appended,
    `last_seen` bumped), new canonical name -> new row. Returns the
    canonical name so callers (openFDA reactive lookup, discovery ingestion)
    can key off it. Never resets/replaces the table — it only grows or
    merges across runs.

    Rejects junk (placebo/comparator/procedure arms, bare cohort labels —
    see app.core.drug_normalization.is_junk_drug_name) before it ever
    enters the cache, returning "" so callers treat it the same as an
    empty/unnormalizable name."""
    if is_junk_drug_name(raw_name):
        return ""

    canonical = normalize_drug_name(raw_name)
    if not canonical:
        return canonical

    record = session.execute(
        select(KnownDrugRecord).where(KnownDrugRecord.canonical_name == canonical)
    ).scalar_one_or_none()

    raw_stripped = raw_name.strip()

    if record is None:
        rxnorm_id = resolve_rxnorm_id(canonical) if resolve_rxnorm else None
        entity_type = "drug_class" if canonical in DRUG_CLASS_ALLOWLIST else "drug"
        record = KnownDrugRecord(
            canonical_name=canonical,
            name_variants=json.dumps([raw_stripped]),
            rxnorm_id=rxnorm_id,
            entity_type=entity_type,
        )
        session.add(record)
    else:
        variants = json.loads(record.name_variants)
        if raw_stripped not in variants:
            variants.append(raw_stripped)
            record.name_variants = json.dumps(variants)
        if record.rxnorm_id is None and resolve_rxnorm:
            record.rxnorm_id = resolve_rxnorm_id(canonical)

    session.commit()
    return canonical


def load_all_known_drugs(session: Session) -> list[str]:
    """Returns every canonical drug name accumulated in the cache so far,
    across all runs — not just the ones discovered in the current run."""
    records = session.execute(select(KnownDrugRecord.canonical_name)).scalars().all()
    return list(records)


def record_source_status(
    session: Session,
    source: str,
    status: str,
    message: str | None = None,
    items_ingested: int = 0,
) -> None:
    """Overwrites the one status row per source (Step 10 fallback
    behavior). Called after every discovery attempt, success or failure, so
    a source that errors out never silently looks like it returned a
    complete result — /status surfaces exactly this."""
    record = session.execute(
        select(IngestionStatusRecord).where(IngestionStatusRecord.source == source)
    ).scalar_one_or_none()

    if record is None:
        record = IngestionStatusRecord(source=source)
        session.add(record)

    record.status = status
    record.message = message
    record.items_ingested = items_ingested
    session.commit()


def load_source_statuses(session: Session) -> list[IngestionStatusRecord]:
    return list(session.execute(select(IngestionStatusRecord)).scalars().all())


def _clean_optional_text(value: str | None) -> str | None:
    """Trims whitespace and collapses an empty/blank string to None.
    Deliberately does NOT lowercase/normalize — unlike primary_condition/
    comorbidities/medications (which are matched against disease/drug text
    elsewhere and so are normalized for that purpose), these are
    descriptive patient-context fields where the user's original casing
    (e.g. 'HER2', 'BRCA1') is worth preserving."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def create_case(
    session: Session,
    primary_condition: str,
    comorbidities: list[str],
    current_medications: list[str],
    *,
    age_group: str | None = None,
    sex: str | None = None,
    disease_stage: str | None = None,
    disease_subtype: str | None = None,
    disease_duration: str | None = None,
    phenotypes: list[str] | None = None,
    previous_treatments: list[dict] | None = None,
    biomarkers: list[dict] | None = None,
    genetic_markers: list[dict] | None = None,
) -> CaseRecord:
    """Free-text case creation — no hardcoded disease/drug lists. Condition
    text is normalized the same way every other disease mention already is
    (`app.core.scoring.normalize`); medication text is normalized the same
    way every other drug mention already is (`normalize_drug_name`) so a
    case's medications line up with `known_drugs`/`documents` entities.

    The richer patient-context parameters are all optional/keyword-only so
    every existing caller (positional primary_condition/comorbidities/
    current_medications only) keeps working unchanged. `phenotypes` are
    disease-like free text, normalized the same way comorbidities are (they
    will need the same downstream matching); `previous_treatments[].name`
    is a drug name, normalized the same way current_medications are.
    Everything else (age_group, sex, disease_stage, disease_subtype,
    disease_duration, biomarkers, genetic_markers) is trimmed but not
    case-folded — see `_clean_optional_text`.
    """
    case = CaseRecord(
        primary_condition=normalize_disease_text(primary_condition),
        age_group=_clean_optional_text(age_group),
        sex=_clean_optional_text(sex),
        disease_stage=_clean_optional_text(disease_stage),
        disease_subtype=_clean_optional_text(disease_subtype),
        disease_duration=_clean_optional_text(disease_duration),
    )
    session.add(case)
    session.flush()  # assigns case.id before children reference it

    for name in comorbidities:
        cleaned = normalize_disease_text(name)
        if cleaned:
            session.add(CaseConditionRecord(case_id=case.id, name=cleaned))

    for name in current_medications:
        cleaned = normalize_drug_name(name)
        if cleaned:
            session.add(CaseMedicationRecord(case_id=case.id, name=cleaned))

    for name in phenotypes or []:
        cleaned = normalize_disease_text(name)
        if cleaned:
            session.add(CasePhenotypeRecord(case_id=case.id, name=cleaned))

    for item in previous_treatments or []:
        name = normalize_drug_name(item.get("name") or "")
        if not name:
            continue
        session.add(
            CasePreviousTreatmentRecord(
                case_id=case.id,
                name=name,
                response=_clean_optional_text(item.get("response")),
            )
        )

    for item in biomarkers or []:
        name = _clean_optional_text(item.get("name"))
        if not name:
            continue
        session.add(
            CaseBiomarkerRecord(
                case_id=case.id, name=name, value=_clean_optional_text(item.get("value"))
            )
        )

    for item in genetic_markers or []:
        gene = _clean_optional_text(item.get("gene"))
        if not gene:
            continue
        session.add(
            CaseGeneticMarkerRecord(
                case_id=case.id,
                gene=gene,
                variant=_clean_optional_text(item.get("variant")),
                note=_clean_optional_text(item.get("note")),
            )
        )

    session.commit()
    session.refresh(case)
    return case


def find_matching_case(
    session: Session,
    primary_condition: str,
    comorbidities: list[str],
    current_medications: list[str],
) -> CaseRecord | None:
    """Duplicate-case guard: finds an existing case whose normalized primary
    condition matches AND whose comorbidity/medication sets match exactly
    (order-independent — free-text entry order shouldn't create a
    "different" case). Only exact-set matches count as a duplicate; a case
    with one extra or missing comorbidity is a genuinely different research
    question, not a duplicate, so it's left alone."""
    normalized_condition = normalize_disease_text(primary_condition)
    target_comorbidities = {normalize_disease_text(c) for c in comorbidities if normalize_disease_text(c)}
    target_medications = {normalize_drug_name(m) for m in current_medications if normalize_drug_name(m)}

    candidates = session.execute(
        select(CaseRecord).where(CaseRecord.primary_condition == normalized_condition)
    ).scalars().all()

    for candidate in candidates:
        existing_comorbidities = set(get_case_conditions(session, candidate.id))
        existing_medications = set(get_case_medications(session, candidate.id))
        if existing_comorbidities == target_comorbidities and existing_medications == target_medications:
            return candidate

    return None


def get_case(session: Session, case_id: int) -> CaseRecord | None:
    return session.get(CaseRecord, case_id)


def list_cases(session: Session) -> list[CaseRecord]:
    """Newest-first — used by the frontend's Cases list and Dashboard
    (Phase 2). Ordered by id, not created_at: SQLite's CURRENT_TIMESTAMP
    default has only second resolution, so two cases created within the
    same second would tie and sort unpredictably on created_at alone; id
    (autoincrement) always reflects creation order exactly. No filtering/
    pagination yet; fine for a case volume this project is expected to see
    in this phase."""
    return list(
        session.execute(
            select(CaseRecord).order_by(CaseRecord.id.desc())
        ).scalars().all()
    )


def get_case_conditions(session: Session, case_id: int) -> list[str]:
    rows = session.execute(
        select(CaseConditionRecord.name).where(CaseConditionRecord.case_id == case_id)
    ).scalars().all()
    return list(rows)


def get_case_medications(session: Session, case_id: int) -> list[str]:
    rows = session.execute(
        select(CaseMedicationRecord.name).where(CaseMedicationRecord.case_id == case_id)
    ).scalars().all()
    return list(rows)


def get_case_phenotypes(session: Session, case_id: int) -> list[str]:
    rows = session.execute(
        select(CasePhenotypeRecord.name).where(CasePhenotypeRecord.case_id == case_id)
    ).scalars().all()
    return list(rows)


def get_case_previous_treatments(session: Session, case_id: int) -> list[dict]:
    rows = session.execute(
        select(CasePreviousTreatmentRecord).where(CasePreviousTreatmentRecord.case_id == case_id)
    ).scalars().all()
    return [{"name": r.name, "response": r.response} for r in rows]


def get_case_biomarkers(session: Session, case_id: int) -> list[dict]:
    rows = session.execute(
        select(CaseBiomarkerRecord).where(CaseBiomarkerRecord.case_id == case_id)
    ).scalars().all()
    return [{"name": r.name, "value": r.value} for r in rows]


def get_case_genetic_markers(session: Session, case_id: int) -> list[dict]:
    rows = session.execute(
        select(CaseGeneticMarkerRecord).where(CaseGeneticMarkerRecord.case_id == case_id)
    ).scalars().all()
    return [{"gene": r.gene, "variant": r.variant, "note": r.note} for r in rows]


def set_case_saved(session: Session, case_id: int, saved: bool) -> CaseRecord | None:
    case = session.get(CaseRecord, case_id)
    if case is None:
        return None
    case.saved = saved
    session.commit()
    session.refresh(case)
    return case


def save_case_analysis(session: Session, case_id: int, result_json: str) -> None:
    """Overwrites the one stored analysis per case — "last analysis
    result," not a history table (see app/models/case.py)."""
    record = session.execute(
        select(CaseAnalysisRecord).where(CaseAnalysisRecord.case_id == case_id)
    ).scalar_one_or_none()

    if record is None:
        record = CaseAnalysisRecord(case_id=case_id, result_json=result_json)
        session.add(record)
    else:
        record.result_json = result_json

    session.commit()


def load_case_analysis(session: Session, case_id: int) -> CaseAnalysisRecord | None:
    return session.execute(
        select(CaseAnalysisRecord).where(CaseAnalysisRecord.case_id == case_id)
    ).scalar_one_or_none()


def save_case_snapshot(session: Session, case_id: int, result_json: str) -> None:
    """Overwrites the one stored snapshot per case — taken when a case is
    saved (see app/models/case.py's CaseSnapshotRecord docstring for why
    this is distinct from the "last analysis")."""
    record = session.execute(
        select(CaseSnapshotRecord).where(CaseSnapshotRecord.case_id == case_id)
    ).scalar_one_or_none()

    if record is None:
        record = CaseSnapshotRecord(case_id=case_id, result_json=result_json)
        session.add(record)
    else:
        record.result_json = result_json

    session.commit()


def load_case_snapshot(session: Session, case_id: int) -> CaseSnapshotRecord | None:
    return session.execute(
        select(CaseSnapshotRecord).where(CaseSnapshotRecord.case_id == case_id)
    ).scalar_one_or_none()


def save_evidence_check(
    session: Session, case_id: int, has_new_evidence: bool, result_json: str
) -> None:
    """Overwrites the one stored evidence-check result per case."""
    record = session.execute(
        select(CaseEvidenceCheckRecord).where(CaseEvidenceCheckRecord.case_id == case_id)
    ).scalar_one_or_none()

    if record is None:
        record = CaseEvidenceCheckRecord(
            case_id=case_id, has_new_evidence=has_new_evidence, result_json=result_json
        )
        session.add(record)
    else:
        record.has_new_evidence = has_new_evidence
        record.result_json = result_json

    session.commit()


def load_evidence_check(session: Session, case_id: int) -> CaseEvidenceCheckRecord | None:
    return session.execute(
        select(CaseEvidenceCheckRecord).where(CaseEvidenceCheckRecord.case_id == case_id)
    ).scalar_one_or_none()


def save_case_research_evidence(
    session: Session,
    *,
    case_id: int,
    query: str,
    source: str,
    source_id: str,
    url: str | None,
    title: str | None,
    date,
    normalized_drugs: list[str],
    normalized_diseases: list[str],
    relationships: list[dict],
) -> None:
    """Append one case-specific runtime-research cache row.

    Rows are append-only: a refresh should preserve what the earlier run
    saw so the caller can compare previous vs. newly retrieved evidence.
    The runtime engine dedupes per run before it calls this function; the
    cache keeps query provenance even if two different queries return the
    same source later.
    """
    session.add(
        CaseResearchEvidenceRecord(
            case_id=case_id,
            query=query,
            source=source,
            source_id=source_id,
            url=url,
            title=title,
            date=date,
            normalized_drugs=json.dumps(normalized_drugs),
            normalized_diseases=json.dumps(normalized_diseases),
            relationships_json=json.dumps(relationships),
        )
    )
    session.commit()


def load_case_research_evidence(session: Session, case_id: int) -> list[CaseResearchEvidenceRecord]:
    return list(
        session.execute(
            select(CaseResearchEvidenceRecord).where(
                CaseResearchEvidenceRecord.case_id == case_id
            )
        ).scalars().all()
    )


def load_all_approved_indications(session: Session) -> list[ApprovedIndication]:
    records = session.execute(select(ApprovedIndicationRecord)).scalars().all()
    return [
        ApprovedIndication(
            drug=r.drug,
            disease=r.disease,
            source=r.source,
            source_id=r.source_id,
            url=r.url,
            contraindications=r.contraindications,
            warnings=r.warnings,
            drug_interactions=r.drug_interactions,
        )
        for r in records
    ]
