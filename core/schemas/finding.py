"""The Finding: one detected leakage issue, with its amount, the rule applied and the evidence.

This is the contract between the checks (core/checks), the API (backend) and the UI. A finding's amount is
either CALCULATED (the rule determines it exactly: duplicate line, limit arithmetic, missed copay) or
SUSPECTED (a pattern that needs a human: near-duplicate, provider outlier, related parties). The two are
never mixed in totals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AmountKind(str, Enum):
    CALCULATED = "calculated"
    SUSPECTED = "suspected"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingStatus(str, Enum):
    OPEN = "open"
    AUTO_APPLIED = "auto_applied"          # calculated, rule-certain, under the auto-triage threshold
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
    CLARIFICATION_REQUESTED = "clarification_requested"


class CheckId(str, Enum):
    # Duplicates (brief scenario 1)
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"                  # same invoice / incident submitted more than once
    DUPLICATE_LINE = "DUPLICATE_LINE"                    # same charge repeated within a claim
    CROSS_CLAIM_DUPLICATE_LINE = "CROSS_CLAIM_DUPLICATE_LINE"  # same charge already paid under another claim
    NEAR_DUPLICATE = "NEAR_DUPLICATE"                    # minor differences in date / amount / reference
    # Policy rules (scenario 2)
    COVERAGE_INACTIVE = "COVERAGE_INACTIVE"              # incident outside the policy period / benefit period
    EXCLUDED_SERVICE = "EXCLUDED_SERVICE"                # policy exclusion clause applies to the line
    NON_PAYABLE_ITEM = "NON_PAYABLE_ITEM"                # consumable / item on the non-payable list
    ROOM_LIMIT_EXCEEDED = "ROOM_LIMIT_EXCEEDED"          # room / ICU charge above the daily limit
    SUBLIMIT_EXCEEDED = "SUBLIMIT_EXCEEDED"              # procedure / benefit sub-limit breached
    BENEFIT_LIMIT_EXCEEDED = "BENEFIT_LIMIT_EXCEEDED"    # annual limit / sum insured exhausted (history-aware)
    OUT_OF_NETWORK = "OUT_OF_NETWORK"                    # provider not in the policy's network
    WAITING_PERIOD = "WAITING_PERIOD"                    # treatment inside a waiting period
    # Settlement arithmetic (scenario 3)
    COPAY_NOT_APPLIED = "COPAY_NOT_APPLIED"
    DEDUCTIBLE_NOT_APPLIED = "DEDUCTIBLE_NOT_APPLIED"
    SETTLEMENT_MISMATCH = "SETTLEMENT_MISMATCH"          # proposed settlement differs from the recalculation
    QUANTITY_VS_STAY = "QUANTITY_VS_STAY"                # per-day items billed for more days than the stay
    DATE_OUTSIDE_EPISODE = "DATE_OUTSIDE_EPISODE"        # line dated outside admission..discharge
    ARITHMETIC_MISMATCH = "ARITHMETIC_MISMATCH"          # qty x rate != amount, or lines != printed total
    # Patterns (scenario 4)
    PROVIDER_PRICE_OUTLIER = "PROVIDER_PRICE_OUTLIER"    # unit price far above peer providers for the code
    RELATED_PARTY_PATTERN = "RELATED_PARTY_PATTERN"      # shared phone / bank / address across claimants
    CONSISTENCY_MISMATCH = "CONSISTENCY_MISMATCH"        # documents disagree (name, policy no, dates, provider)
    # Evidence (scenario 5)
    MISSING_EVIDENCE = "MISSING_EVIDENCE"                # required document / field absent: ask, do not invent


class CheckCategory(str, Enum):
    DUPLICATE = "duplicate"
    POLICY_RULE = "policy_rule"
    SETTLEMENT = "settlement"
    PATTERN = "pattern"
    EVIDENCE = "evidence"


CHECK_CATEGORY = {
    CheckId.DUPLICATE_CLAIM: CheckCategory.DUPLICATE, CheckId.DUPLICATE_LINE: CheckCategory.DUPLICATE,
    CheckId.CROSS_CLAIM_DUPLICATE_LINE: CheckCategory.DUPLICATE, CheckId.NEAR_DUPLICATE: CheckCategory.DUPLICATE,
    CheckId.COVERAGE_INACTIVE: CheckCategory.POLICY_RULE, CheckId.EXCLUDED_SERVICE: CheckCategory.POLICY_RULE,
    CheckId.NON_PAYABLE_ITEM: CheckCategory.POLICY_RULE, CheckId.ROOM_LIMIT_EXCEEDED: CheckCategory.POLICY_RULE,
    CheckId.SUBLIMIT_EXCEEDED: CheckCategory.POLICY_RULE, CheckId.BENEFIT_LIMIT_EXCEEDED: CheckCategory.POLICY_RULE,
    CheckId.OUT_OF_NETWORK: CheckCategory.POLICY_RULE, CheckId.WAITING_PERIOD: CheckCategory.POLICY_RULE,
    CheckId.COPAY_NOT_APPLIED: CheckCategory.SETTLEMENT, CheckId.DEDUCTIBLE_NOT_APPLIED: CheckCategory.SETTLEMENT,
    CheckId.SETTLEMENT_MISMATCH: CheckCategory.SETTLEMENT, CheckId.QUANTITY_VS_STAY: CheckCategory.SETTLEMENT,
    CheckId.DATE_OUTSIDE_EPISODE: CheckCategory.SETTLEMENT, CheckId.ARITHMETIC_MISMATCH: CheckCategory.SETTLEMENT,
    CheckId.PROVIDER_PRICE_OUTLIER: CheckCategory.PATTERN, CheckId.RELATED_PARTY_PATTERN: CheckCategory.PATTERN,
    CheckId.CONSISTENCY_MISMATCH: CheckCategory.PATTERN, CheckId.MISSING_EVIDENCE: CheckCategory.EVIDENCE,
}


class Evidence(BaseModel):
    """One piece of supporting record: where it is and what it says."""
    source: str = Field(..., description="claim | invoice_line | policy | history | document | config")
    ref: str = Field(..., description="line_id, invoice number, clause id, history claim id, document id + page")
    quote: str = Field(default="", description="The value or text as it appears in the record")


class ClauseRef(BaseModel):
    """The policy clause the finding rests on (from the policy RAG)."""
    clause_id: str = Field(..., description="Clause number as printed in the policy wording")
    text: str = Field(..., description="The clause text")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Retrieval similarity 0..1")


class Finding(BaseModel):
    finding_id: str = Field(..., description="Stable id: <claim_id>:<check_id>:<n>")
    claim_id: str = Field(..., description="The claim the finding belongs to")
    check_id: CheckId = Field(..., description="Which check raised it")
    category: CheckCategory = Field(..., description="Dashboard grouping")
    severity: Severity = Field(..., description="low / medium / high")
    amount: float = Field(default=0.0, ge=0.0, description="Potential excess amount in the claim's currency")
    amount_kind: AmountKind = Field(..., description="calculated (exact by rule) or suspected (needs a human)")
    currency: str = Field(..., description="ISO code, e.g. INR, AED")
    rule_id: str = Field(..., description="Config or policy rule id applied, e.g. ROOM_RENT_LIMIT, CLAUSE 4.2")
    rule_text: str = Field(..., description="The rule in one sentence, as configured")
    calculation: str = Field(default="", description="The arithmetic, e.g. '(5,000 - 3,000) x 3 days = 6,000'")
    reason: str = Field(default="", description="Plain-English explanation for the reviewer")
    line_ids: List[str] = Field(default_factory=list, description="Invoice lines involved")
    evidence: List[Evidence] = Field(default_factory=list, description="Supporting records")
    clause: Optional[ClauseRef] = Field(default=None, description="Policy clause, when the rule comes from wording")
    related_claim_ids: List[str] = Field(default_factory=list, description="Other claims involved (duplicates, history)")
    status: FindingStatus = Field(default=FindingStatus.OPEN, description="Review state")
    recommendation: Optional[str] = Field(default=None, description="Investigator agent: confirm | dismiss | clarify (suspected findings only)")
    recommendation_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Investigator's confidence")
    recommendation_note: str = Field(default="", description="Investigator's note for the reviewer, with what it checked")
    reviewer_note: str = Field(default="", description="Reviewer's note")
    corrected_amount: Optional[float] = Field(default=None, description="Amount set by the reviewer on 'correct'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When it was raised")

    @property
    def effective_amount(self) -> float:
        """What the settlement deducts: a reviewer's correction or confirmation wins; an open or auto-applied
        finding counts only when its amount is calculated; dismissed or awaiting clarification counts nothing."""
        if self.status in (FindingStatus.DISMISSED, FindingStatus.CLARIFICATION_REQUESTED):
            return 0.0
        if self.status == FindingStatus.CORRECTED:
            return self.corrected_amount if self.corrected_amount is not None else self.amount
        if self.status == FindingStatus.CONFIRMED:
            return self.amount
        return self.amount if self.amount_kind == AmountKind.CALCULATED else 0.0


class ValidationIssue(BaseModel):
    """One problem found while ingesting a file; invalid rows are reported, never silently dropped."""
    file: str = Field(..., description="Uploaded file name")
    row: Optional[int] = Field(default=None, description="1-based row number in the file")
    field: str = Field(default="", description="Column / field with the problem")
    problem: str = Field(..., description="What is wrong, in plain English")
    accepted: bool = Field(default=False, description="True when the row was still accepted (warning only)")
