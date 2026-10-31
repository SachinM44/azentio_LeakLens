"""Page classification output: one record per page with its document type and boundary signals;
the document-type list is in document_types.json."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator

DOCUMENT_TYPES: List[str] = json.loads((Path(__file__).with_name("document_types.json")).read_text(encoding="utf-8"))
DocumentType = Enum("DocumentType", {value.upper(): value for value in DOCUMENT_TYPES}, type=str)
BILL_TYPES = {"itemized_final_hospital_bill", "summary_final_hospital_bill", "interim_running_bill",
              "medicine_pharmacy_bills"}


class PageClassification(BaseModel):
    """Per-page detection and boundary signals."""
    page_index: int = Field(..., ge=0)
    document_type: DocumentType = Field(
        ..., description="Document type for this page. other_documents is always valid when no specific category clearly applies.")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    is_first_page: bool = False
    is_last_page: bool = False
    continues_previous: bool = False
    internal_pagination: Optional[str] = Field(
        default=None, description='Printed page numbering only (never PDF order). Prefer "Page N of M"; null if absent')
    document_identifier: Optional[str] = Field(
        default=None, description="Primary bill/report/admission/UHID/accession id visible on this page")
    logical_document_id: Optional[str] = Field(
        default=None, description="Stable id for the logical document instance; reuse across non-adjacent pages of the same bill/report")
    order_within_document: Optional[int] = Field(default=None, ge=1, description="1-based order of this page within its logical document")
    document_date: Optional[str] = Field(
        default=None, description="Primary date on this page (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS when time shown)")
    observed_signals: List[str] = Field(default_factory=list, description="Visible cues: pagination:, doc_id:, header: lines first")
    new_document_evidence: List[str] = Field(default_factory=list, description="Cues that this page starts a new logical document")
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _unknown_type_is_other(cls, data: Any) -> Any:
        # A missing or unknown type becomes other_documents .
        if isinstance(data, dict):
            raw = str(data.get("document_type") or "").strip().lower()
            if raw not in DOCUMENT_TYPES:
                data = {**data, "document_type": "other_documents"}
        return data


class PageClassificationBatch(BaseModel):
    """One record per page image in the request."""
    pages: List[PageClassification] = Field(default_factory=list, description="One record per page (0-based global page_index)")
    notes: Optional[str] = Field(None, description="Optional remarks only (e.g. scan quality); must not be used to omit pages")
