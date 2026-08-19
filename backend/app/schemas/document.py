"""Common data shapes shared by every ingestion source and the comparison engine.

See /shared/schema.md for the plain-language description of these fields.
"""
from __future__ import annotations

from datetime import date as date_
from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["clinicaltrials", "biorxiv", "medrxiv", "manual"]
GroundTruthSource = Literal["openfda", "manual"]


class Document(BaseModel):
    """A single observed drug-disease mention from any source."""

    drug: str
    disease: str
    source: SourceType
    source_id: str
    phase: Optional[str] = None
    date: Optional[date_] = None
    url: Optional[str] = None
    num_mentions: int = 1

    def normalized_drug(self) -> str:
        return self.drug.strip().lower()

    def normalized_disease(self) -> str:
        return self.disease.strip().lower()


class ApprovedIndication(BaseModel):
    """Ground truth: a disease a drug is already FDA-approved to treat."""

    drug: str
    disease: str
    source: GroundTruthSource = "openfda"
    source_id: Optional[str] = None
    url: Optional[str] = None

    def normalized_drug(self) -> str:
        return self.drug.strip().lower()

    def normalized_disease(self) -> str:
        return self.disease.strip().lower()


class Signal(BaseModel):
    """A flagged repurposing candidate: drug being studied for a disease it
    is not yet approved for."""

    drug: str
    disease: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    supporting_documents: list[Document] = Field(default_factory=list)
    approved_for: list[str] = Field(default_factory=list)
