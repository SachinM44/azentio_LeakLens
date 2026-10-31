"""The recalculated settlement for one claim: requested → deductions by finding → deductible → copay → payable,
compared with the handler's proposed settlement when one was supplied.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Deduction(BaseModel):
    finding_id: str = Field(..., description="Finding that caused the deduction")
    check_id: str = Field(..., description="Check id")
    amount: float = Field(..., description="Amount deducted (the finding's effective amount)")
    reason: str = Field(default="", description="One line")


class Settlement(BaseModel):
    claim_id: str
    currency: str
    requested_amount: float = Field(..., description="As claimed")
    lines_total: float = Field(..., description="Sum of invoice lines")
    deductions: List[Deduction] = Field(default_factory=list, description="Calculated deductions, by finding")
    after_deductions: float = Field(..., description="lines_total - deductions")
    deductible_amount: float = Field(default=0.0, description="Deductible applied")
    copay_pct: float = Field(default=0.0, description="Copay % applied")
    copay_amount: float = Field(default=0.0, description="Copay amount")
    benefit_cap_applied: float = Field(default=0.0, description="Reduction from the annual limit / sum insured")
    payable: float = Field(..., description="Insurer pays")
    patient_pays: float = Field(..., description="Deductible + copay + non-payable items")
    proposed_settlement: Optional[float] = Field(default=None, description="Handler's proposed figure, if any")
    difference: Optional[float] = Field(default=None, description="proposed - payable (positive = overpayment)")
    steps: List[str] = Field(default_factory=list, description="The calculation, one line per step, for the UI")
