"""The master dataset: the one shape every check runs on, whether the claim arrived as CSV/JSON rows or as
scanned documents. Structured uploads map onto it directly; the document path fills it after classification
review and digitisation.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    INPATIENT = "inpatient"
    OUTPATIENT = "outpatient"
    PHARMACY = "pharmacy"
    DAYCARE = "daycare"
    MOTOR = "motor"


class LineCategory(str, Enum):
    ROOM = "room"
    ICU = "icu"
    SURGERY = "surgery"
    PROFESSIONAL_FEES = "professional fees"
    LAB = "lab"
    RADIOLOGY = "radiology"
    PHARMA = "pharma"
    MEDICAL = "medical"          # consumables, implants, equipment
    SERVICES = "services"        # nursing, OT charges, admin
    TAXES = "taxes"
    PARTS = "parts"              # motor
    LABOUR = "labour"            # motor
    OTHER = "other"


class InvoiceLine(BaseModel):
    line_id: str = Field(..., description="Stable id: <claim_id>:<invoice_no>:<serial_no>")
    claim_id: str = Field(..., description="Owning claim")
    invoice_no: str = Field(..., description="Invoice / bill number as printed")
    serial_no: int = Field(..., ge=1, description="1-based position on the invoice")
    service_date: Optional[date] = Field(default=None, description="Date the service was given")
    code: Optional[str] = Field(default=None, description="Service / drug / CPT code as printed")
    code_system: Optional[str] = Field(default=None, description="CPT | HCPCS | drug | service | internal")
    description: str = Field(..., description="Service description as printed")
    category: Optional[LineCategory] = Field(default=None, description="Bill category used by the rules")
    quantity: float = Field(default=1.0, description="Units / days / sessions")
    unit_price: Optional[float] = Field(default=None, description="Price per unit")
    amount: float = Field(..., description="Line total as printed (may be negative for returns / discounts)")
    provider_id: Optional[str] = Field(default=None, description="Provider that billed the line")
    document_id: Optional[str] = Field(default=None, description="Source document when read from a scan")
    page: Optional[int] = Field(default=None, description="Page of the source document")
    notes: Optional[str] = Field(default=None, description="Anything the reader flagged on this line")


class Claim(BaseModel):
    claim_id: str = Field(..., description="Claim identifier")
    policy_number: str = Field(..., description="Policy the claim is made under")
    product_id: str = Field(..., description="Product / rule book id, e.g. IN-HEALTH-RETAIL")
    claimant_id: str = Field(..., description="Member / insured id")
    claimant_name: str = Field(default="", description="Synthetic name; shown as initials in the UI")
    provider_id: str = Field(..., description="Hospital / clinic / garage id")
    provider_name: str = Field(default="", description="Provider name")
    claim_type: ClaimType = Field(..., description="inpatient | outpatient | pharmacy | daycare | motor")
    incident_date: date = Field(..., description="Date of loss / admission / visit")
    admission_date: Optional[date] = Field(default=None, description="Admission (inpatient)")
    discharge_date: Optional[date] = Field(default=None, description="Discharge (inpatient)")
    diagnosis: Optional[str] = Field(default=None, description="Diagnosis / procedure text")
    diagnosis_code: Optional[str] = Field(default=None, description="ICD-10 when given")
    room_category: Optional[str] = Field(default=None, description="Room class occupied")
    requested_amount: float = Field(..., ge=0, description="Amount claimed")
    proposed_settlement: Optional[float] = Field(default=None, description="Settlement proposed by the handler, if any")
    currency: str = Field(..., description="INR, AED, ...")
    invoice_numbers: List[str] = Field(default_factory=list, description="Invoices attached")
    submitted_at: Optional[datetime] = Field(default=None, description="Submission time")
    status: str = Field(default="ingested", description="ingested | classified | extracted | checked | reviewed | settled")
    source: str = Field(default="structured", description="structured | documents | mixed")
    contact_phone: Optional[str] = Field(default=None, description="Synthetic; used by the related-party pattern")
    bank_account: Optional[str] = Field(default=None, description="Synthetic; used by the related-party pattern")
    address: Optional[str] = Field(default=None, description="Synthetic; used by the related-party pattern")
    extra: Dict[str, str] = Field(default_factory=dict, description="Any other columns from the upload, kept as text")


class Sublimit(BaseModel):
    sublimit_id: str = Field(..., description="e.g. CATARACT, MATERNITY, PHYSIO_SESSIONS")
    name: str = Field(..., description="Display name")
    limit: float = Field(..., description="Amount or count limit")
    basis: str = Field(default="per_claim", description="per_claim | per_year | per_day | sessions_per_year")
    keywords: List[str] = Field(default_factory=list, description="Description keywords that trigger it")
    codes: List[str] = Field(default_factory=list, description="Codes that trigger it")
    clause_id: Optional[str] = Field(default=None, description="Policy clause number")


class Exclusion(BaseModel):
    exclusion_id: str = Field(..., description="e.g. COSMETIC, DENTAL, OPD")
    text: str = Field(..., description="Exclusion wording")
    keywords: List[str] = Field(default_factory=list, description="Description keywords")
    codes: List[str] = Field(default_factory=list, description="Codes")
    clause_id: Optional[str] = Field(default=None, description="Policy clause number")


class Deductible(BaseModel):
    amount: float = Field(default=0.0, description="Deductible amount")
    basis: str = Field(default="per_claim", description="per_claim | per_visit | per_year")


class Copay(BaseModel):
    inpatient_pct: float = Field(default=0.0, description="Copay % on inpatient claims")
    outpatient_pct: float = Field(default=0.0, description="Copay % on outpatient claims")
    pharmacy_pct: float = Field(default=0.0, description="Copay % on pharmacy lines")


class Policy(BaseModel):
    policy_number: str = Field(..., description="Policy number")
    product_id: str = Field(..., description="Rule book id")
    holder_id: str = Field(..., description="Policyholder id")
    members: List[str] = Field(default_factory=list, description="Covered member ids")
    start_date: date = Field(..., description="Cover start")
    end_date: date = Field(..., description="Cover end")
    currency: str = Field(..., description="INR, AED, ...")
    annual_limit: float = Field(..., description="Sum insured / annual benefit limit per member")
    deductible: Deductible = Field(default_factory=Deductible, description="Deductible rule")
    copay: Copay = Field(default_factory=Copay, description="Copay rules")
    room_rent_limit_per_day: Optional[float] = Field(default=None, description="Daily room limit (absolute)")
    icu_limit_per_day: Optional[float] = Field(default=None, description="Daily ICU limit (absolute)")
    sublimits: List[Sublimit] = Field(default_factory=list, description="Sub-limits")
    exclusions: List[Exclusion] = Field(default_factory=list, description="Exclusions")
    non_payable_items: List[str] = Field(default_factory=list, description="Consumables / items never paid")
    network_provider_ids: List[str] = Field(default_factory=list, description="Empty = any provider allowed")
    waiting_period_days: int = Field(default=0, description="General waiting period from start_date")
    ped_waiting_days: int = Field(default=0, description="Pre-existing disease waiting period")
    declared_ped: List[str] = Field(default_factory=list, description="Declared pre-existing conditions (keywords)")
    proportionate_deduction: bool = Field(default=False, description="Room over limit scales the other charges")


class HistoryRecord(BaseModel):
    """An earlier claim and what was paid on it; the benefit-limit and cross-claim duplicate checks read these."""
    claim_id: str = Field(..., description="Earlier claim id")
    policy_number: str = Field(..., description="Policy")
    claimant_id: str = Field(..., description="Member")
    provider_id: Optional[str] = Field(default=None, description="Provider")
    incident_date: date = Field(..., description="Date of loss / admission")
    invoice_numbers: List[str] = Field(default_factory=list, description="Invoices on that claim")
    requested_amount: float = Field(..., description="Requested")
    approved_amount: float = Field(..., description="Approved")
    paid_amount: float = Field(..., description="Paid")
    paid_on: Optional[date] = Field(default=None, description="Payment date")
    lines: List[InvoiceLine] = Field(default_factory=list, description="Paid lines, when available")
    contact_phone: Optional[str] = Field(default=None, description="Synthetic; related-party pattern")
    bank_account: Optional[str] = Field(default=None, description="Synthetic; related-party pattern")
    address: Optional[str] = Field(default=None, description="Synthetic; related-party pattern")


class ProductConfig(BaseModel):
    """Per-insurer / per-product configuration edited on the Config screen."""
    product_id: str = Field(..., description="e.g. IN-HEALTH-RETAIL")
    name: str = Field(..., description="Display name")
    insurer: str = Field(..., description="Synthetic insurer name")
    market: str = Field(..., description="IN | AE | ...")
    currency: str = Field(..., description="INR | AED")
    required_documents: Dict[str, List[str]] = Field(default_factory=dict, description="claim_type -> document types")
    non_payable_items: List[str] = Field(default_factory=list, description="Default non-payable list")
    auto_triage_threshold: float = Field(default=0.0, description="Calculated findings at or under this are auto-applied")
    near_duplicate_amount_tolerance_pct: float = Field(default=2.0, description="Near-duplicate amount tolerance")
    near_duplicate_days: int = Field(default=3, description="Near-duplicate date window")
    repeatable_service_codes: List[str] = Field(default_factory=list, description="Codes that legitimately repeat (physio...)")
    provider_outlier_zscore: float = Field(default=2.5, description="Price outlier threshold")
    policy_wording_file: Optional[str] = Field(default=None, description="data/policies/<file>.md with numbered clauses")


class MasterRecord(BaseModel):
    """Everything a check needs for one claim, loaded once."""
    claim: Claim
    lines: List[InvoiceLine] = Field(default_factory=list)
    policy: Optional[Policy] = None
    history: List[HistoryRecord] = Field(default_factory=list, description="Earlier claims of the same member / policy")
    product: Optional[ProductConfig] = None
    documents: List[str] = Field(default_factory=list, description="Document ids attached")
    document_types: Dict[str, str] = Field(default_factory=dict, description="document id -> confirmed type")
    document_facts: Dict[str, str] = Field(default_factory=dict, description="Header facts read off the documents: "
                                           "claimant_name, policy_number, provider_name, admission_date, discharge_date, "
                                           "invoice_no, net_payable (as printed)")
    printed_total: Optional[float] = Field(default=None, description="Net payable printed on the bill (document path)")
    reconciled: Optional[bool] = Field(default=None, description="Lines add up to the printed total within 1")
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
