"""Document digitisation output: bill line items, header fields, clinical metadata and billing amounts."""
import logging
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

logger = logging.getLogger(__name__)


def remove_additional_properties_from_schema(schema: dict, model_class: type) -> None:
    """
    Custom JSON schema modifier that removes additionalProperties from object schemas.
    This is required because Gemini API doesn't support additionalProperties.
    """
    def _remove_recursive(s: dict) -> None:
        """Recursively remove additionalProperties from nested schemas."""
        if not isinstance(s, dict):
            return

        s.pop("additionalProperties", None)

        if "properties" in s and isinstance(s["properties"], dict):
            for prop_schema in s["properties"].values():
                if isinstance(prop_schema, dict):
                    _remove_recursive(prop_schema)

        if "items" in s:
            if isinstance(s["items"], dict):
                _remove_recursive(s["items"])
            elif isinstance(s["items"], list):
                for item in s["items"]:
                    if isinstance(item, dict):
                        _remove_recursive(item)

        if "anyOf" in s:
            for any_of_item in s["anyOf"]:
                if isinstance(any_of_item, dict):
                    _remove_recursive(any_of_item)

        if "oneOf" in s:
            for one_of_item in s["oneOf"]:
                if isinstance(one_of_item, dict):
                    _remove_recursive(one_of_item)

        if "allOf" in s:
            for all_of_item in s["allOf"]:
                if isinstance(all_of_item, dict):
                    _remove_recursive(all_of_item)

    _remove_recursive(schema)


class DigitizedBillItem(BaseModel):
    """Bill item with billing type tag and mapped room category."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    item_name: str = Field(
        ...,
        description="Name or description of the bill item"
    )
    item_type: str = Field(
        ...,
        description="Billing type from bill_category_list in module config. MUST be exactly one of the values from bill_category_list - no other categories allowed. Extract the authorized list from module_configs (module_name='non_medico_preprocessing', document_name='bill_category_list') and use ONLY those categories."
    )
    quantity: Optional[float] = Field(
        default=None,
        description="Quantity of the item"
    )
    unit_price: Optional[float] = Field(
        default=None,
        description="Unit price of the item"
    )
    total_amount: float = Field(
        ...,
        description="Total amount for this line item (use negative values when the bill shows discounts as negative)"
    )
    item_code: Optional[str] = Field(
        default=None,
        description="Item code if available"
    )
    item_date: Optional[str] = Field(
        default=None,
        description="Date of usage for this item in ISO 8601 format (YYYY-MM-DD)"
    )
    room_category: Optional[str] = Field(
        default=None,
        description="Mapped room category from insurer's room category list (if applicable for this item)"
    )
    original_room_name: Optional[str] = Field(
        default=None,
        description="Original room name from hospital document (before mapping)"
    )
    page_number: Optional[int] = Field(
        default=None,
        description="1-based page number within the source bill document where this line was extracted",
    )
    section_name: Optional[str] = Field(
        default=None,
        description="Printed section/category header this line sits under on the bill (copy VERBATIM, e.g. 'PHARMACY - S (ISSUE)', 'Lab Charges'); omit when the bill has no section headers",
    )
    repair_index: Optional[int] = Field(
        default=None,
        description="When repair_mode is true in the payload, index of the line being re-extracted (must match lines_to_repair.repair_index)",
    )


class DigitizedField(BaseModel):
    """Extracted field from a document."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    field_id: str = Field(..., description="Technical field name/ID")
    field_alias: str = Field(..., description="Human-readable field alias")
    value: Optional[str] = Field(None, description="Extracted field value")


class DigitizedBillData(BaseModel):
    """Digitized data for bill documents."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    bill_items: List[DigitizedBillItem] = Field(
        default_factory=list,
        description="All bill lines from the document (1:1): charges, taxes (CGST/SGST/IGST/GST), discounts, and adjustments — used to verify bill total"
    )


class CheckboxGroup(BaseModel):
    """One checkbox / radio-button group printed on a form (e.g. 'Type of Admission')."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    label: str = Field(..., description="The printed question / label the boxes belong to, exactly as printed")
    options: List[str] = Field(
        default_factory=list,
        description="ALL printed options of the group in reading order (e.g. ['Emergency', 'Planned', 'Day care', 'Maternity'])",
    )
    ticked: List[str] = Field(
        default_factory=list,
        description="The option(s) visibly marked (tick, cross, fill, circle, pencil mark). Empty list when none is marked. Never infer.",
    )


class CheckboxVerifyResponse(BaseModel):
    """Output of the per-tick verification question (checkbox_pass.py)."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    verdict: str = Field(
        default="unclear",
        description="'marked' = a deliberate tick/cross/fill/circle on or hugging THAT box; 'passing' = the ink is a stroke passing through / handwriting overlapping on its way elsewhere, or the box is empty; 'unclear' = cannot tell",
    )
    reason: str = Field(default="", description="One short line: what you see at that box")


class CheckboxPassResponse(BaseModel):
    """Output of the focused per-page checkbox read (checkbox_pass.py)."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    success: bool = Field(default=True, description="False only if the page could not be read at all")
    message: str = Field(default="", description="One short line on the page's legibility / ambiguous marks")
    checkbox_groups: List[CheckboxGroup] = Field(
        default_factory=list,
        description="Every checkbox / radio group printed on the page, ticked or not",
    )


class DigitizedDocumentData(BaseModel):
    """Digitized data for non-bill documents."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    fields: List[DigitizedField] = Field(
        default_factory=list,
        description="Extracted fields from the document"
    )
    checkbox_groups: List[CheckboxGroup] = Field(
        default_factory=list,
        description=(
            "EVERY checkbox / radio-button group printed on the document, ticked OR NOT — one entry "
            "per group (claim form, pre-authorisation form, KYC / consent / undertaking forms, "
            "discharge summary, certificates). A checkbox is a small square next to an option WORD "
            "(Yes / No / Male / Female / Network / Emergency ...); rows of empty letter cells for "
            "handwriting are NOT checkboxes. Empty list only when the document has no checkbox groups."
        ),
    )


class PatientDetails(BaseModel):
    """Patient demographics extracted from a clinical document."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    name: Optional[str] = Field(default=None, description="Patient name")
    age: Optional[str] = Field(default=None, description="Patient age")
    gender: Optional[str] = Field(default=None, description="Patient gender")
    patient_id: Optional[str] = Field(
        default=None, description="Patient ID / UHID / MRN"
    )
    address: Optional[str] = Field(default=None, description="Patient address")


class DiagnosisDetail(BaseModel):
    """Single diagnosis entry from a clinical document (max 3 per document)."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    display: str = Field(..., description="Diagnosis text as written in the document")
    rank: Optional[int] = Field(
        default=None, description="Diagnosis rank: 1=primary, 2=secondary, 3=tertiary"
    )
    organ: Optional[str] = Field(default=None, description="Affected organ if documented")
    site: Optional[str] = Field(default=None, description="Anatomical site if documented")
    indication: Optional[str] = Field(
        default=None, description="Clinical indication if documented"
    )
    severity: Optional[str] = Field(
        default=None, description="Severity or stage if documented"
    )


class ProcedureDetail(BaseModel):
    """Procedure or intervention extracted from a clinical document."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    display: str = Field(..., description="Procedure text as written in the document")
    is_primary: Optional[bool] = Field(
        default=None, description="True if this is the primary procedure"
    )
    organ: Optional[str] = Field(default=None, description="Affected organ if documented")
    site: Optional[str] = Field(default=None, description="Anatomical site if documented")


class DayWiseClinicalNote(BaseModel):
    """Clinical notes for a specific date."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    date: str = Field(..., description="Date of notes in ISO YYYY-MM-DD format")
    notes: str = Field(..., description="Clinical notes for that date")


class ImagingFinding(BaseModel):
    """Detailed description of a medical image, scan, or visual diagnostic finding."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    image_type: Optional[str] = Field(
        default=None,
        description="Modality or image type (e.g. X-ray, CT, MRI, ultrasound, ECG, PET)",
    )
    body_part: Optional[str] = Field(
        default=None, description="Anatomical region or body part shown"
    )
    view: Optional[str] = Field(
        default=None,
        description="Projection or view (e.g. AP, PA, lateral, axial, sagittal)",
    )
    description: str = Field(
        ...,
        description=(
            "Exhaustive visual description: anatomy visible, abnormalities, density/"
            "signal patterns, measurements, annotations, and clinically relevant details"
        ),
    )
    printed_impression: Optional[str] = Field(
        default=None,
        description="Radiologist/doctor impression or conclusion text linked to this image",
    )
    page_number: Optional[int] = Field(
        default=None, description="1-based page number where the image appears"
    )


class BillingAmounts(BaseModel):
    """Document-level billing totals visible on a clinical document."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    grand_total: Optional[float] = Field(default=None, description="Grand total amount")
    net_payable: Optional[float] = Field(default=None, description="Net payable amount")
    total_discount: Optional[float] = Field(default=None, description="Total discount")
    total_tax: Optional[float] = Field(default=None, description="Total tax amount")
    room_charges: Optional[float] = Field(default=None, description="Room charges total")
    estimated_cost: Optional[float] = Field(
        default=None, description="Estimated cost if shown"
    )


class DocumentClinicalMetadata(BaseModel):
    """Structured clinical metadata per clinical document."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    patient_details: Optional[PatientDetails] = Field(
        default=None, description="Patient demographics"
    )
    diagnosis_details: List[DiagnosisDetail] = Field(
        default_factory=list,
        description="Up to 3 ranked diagnoses from the document"
    )
    procedures: List[ProcedureDetail] = Field(
        default_factory=list, description="Procedures or interventions"
    )
    line_of_treatment: Optional[str] = Field(
        default=None, description="Line of treatment / treatment summary"
    )
    doctor_name: Optional[str] = Field(
        default=None, description="Treating or attending doctor name"
    )
    room_category: Optional[str] = Field(
        default=None, description="Room category or ward type"
    )
    length_of_stay: Optional[int] = Field(
        default=None, description="Length of stay in days"
    )
    date_of_admission: Optional[str] = Field(
        default=None, description="Admission date ISO YYYY-MM-DD"
    )
    date_of_discharge: Optional[str] = Field(
        default=None, description="Discharge date ISO YYYY-MM-DD"
    )
    dates: List[str] = Field(
        default_factory=list,
        description="Other relevant dates visible on the document (ISO YYYY-MM-DD)",
    )
    day_wise_clinical_notes: List[DayWiseClinicalNote] = Field(
        default_factory=list,
        description="Day-wise progress or clinical notes when present",
    )
    imaging_findings: List[ImagingFinding] = Field(
        default_factory=list,
        description=(
            "Detailed descriptions of embedded medical images, scans, tracings, "
            "and visual diagnostic content"
        ),
    )
    billing_amounts: Optional[BillingAmounts] = Field(
        default=None, description="Document-level billing totals if visible"
    )

    @field_validator("diagnosis_details")
    @classmethod
    def cap_diagnosis_details(cls, value: List[DiagnosisDetail]) -> List[DiagnosisDetail]:
        """Limit to at most 3 diagnoses per document."""
        return value[:3]


class HeaderFieldVerifyData(BaseModel):
    """The requested header fields of a bill, re-read on their own (header_field_verify.py)."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    fields: List[DigitizedField] = Field(
        default_factory=list,
        description="One row per requested field_id"
    )


class HeaderFieldVerifyResponse(BaseModel):
    """Answer shape of the compact header verify agent: the requested fields and nothing else."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    success: bool = Field(
        default=True,
        description="False only if the pages could not be read at all"
    )
    message: str = Field(
        default="",
        description="One short line on what was verified"
    )
    document_data: HeaderFieldVerifyData = Field(
        default_factory=HeaderFieldVerifyData,
        description="The requested fields"
    )


class FileDigitizationResponse(BaseModel):
    """Response from file digitization agent."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    success: bool = Field(
        ...,
        description="Whether digitization was successful"
    )
    document_type: str = Field(
        ...,
        description="Type of document that was digitized"
    )
    document_date: Optional[str] = Field(
        default=None,
        description="Primary document date from the document body (ISO YYYY-MM-DD) if visible",
    )
    admission_date: Optional[str] = Field(
        default=None,
        description="Admission date from document when present (ISO YYYY-MM-DD)",
    )
    discharge_date: Optional[str] = Field(
        default=None,
        description="Discharge date from document when present (ISO YYYY-MM-DD)",
    )
    bill_data: Optional[DigitizedBillData] = Field(
        default=None,
        description="Digitized bill data (if document is a bill)"
    )
    document_data: Optional[DigitizedDocumentData] = Field(
        default=None,
        description="Digitized document data (if document is not a bill)"
    )
    clinical_metadata: Optional[DocumentClinicalMetadata] = Field(
        default=None,
        description="Structured clinical metadata (clinical document types only)",
    )
    message: str = Field(
        ...,
        description="Message about the digitization process"
    )
