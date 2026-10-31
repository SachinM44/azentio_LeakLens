"""The recommended settlement correction for every finding: the amount it touches, before and after.

original = the finding's lines; else the proposed settlement (settlement checks); else the requested amount.
corrected = original - the finding's amount.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from core.checks._common import money
from core.checks.settlement import SETTLEMENT_CHECKS
from core.schemas.finding import CheckId, Correction, Finding
from core.schemas.master import MasterRecord

ACTIONS: Dict[CheckId, Tuple[str, str]] = {
    CheckId.DUPLICATE_CLAIM: ("reject_claim", "Reject the claim as a duplicate"),
    CheckId.DUPLICATE_LINE: ("remove_line", "Remove the repeated line"),
    CheckId.CROSS_CLAIM_DUPLICATE_LINE: ("remove_line", "Remove the line already paid under another claim"),
    CheckId.NEAR_DUPLICATE: ("hold_for_investigation", "Hold for investigation as a possible duplicate"),
    CheckId.COVERAGE_INACTIVE: ("reject_claim", "Reject: the incident is outside the cover period"),
    CheckId.EXCLUDED_SERVICE: ("remove_line", "Remove the excluded service"),
    CheckId.NON_PAYABLE_ITEM: ("remove_line", "Remove the non-payable item"),
    CheckId.ROOM_LIMIT_EXCEEDED: ("cap_room", "Cap the room charge at the daily limit"),
    CheckId.SUBLIMIT_EXCEEDED: ("cap_sublimit", "Cap the charge at the sub-limit"),
    CheckId.BENEFIT_LIMIT_EXCEEDED: ("cap_annual_limit", "Cap the payment at the remaining annual limit"),
    CheckId.OUT_OF_NETWORK: ("reject_claim", "Reject: the provider is outside the network"),
    CheckId.WAITING_PERIOD: ("reject_claim", "Reject: treatment inside the waiting period"),
    CheckId.COPAY_NOT_APPLIED: ("apply_copay", "Apply the copay to the settlement"),
    CheckId.DEDUCTIBLE_NOT_APPLIED: ("apply_deductible", "Apply the deductible to the settlement"),
    CheckId.SETTLEMENT_MISMATCH: ("recalc_settlement", "Pay the recalculated settlement"),
    CheckId.QUANTITY_VS_STAY: ("reduce_days", "Reduce the billed days to the length of stay"),
    CheckId.DATE_OUTSIDE_EPISODE: ("remove_line", "Remove the line dated outside the stay"),
    CheckId.ARITHMETIC_MISMATCH: ("fix_arithmetic", "Pay quantity x rate, not the printed amount"),
    CheckId.PROVIDER_PRICE_OUTLIER: ("pay_at_peer_median", "Pay at the peer median price"),
    CheckId.RELATED_PARTY_PATTERN: ("hold_for_investigation", "Hold for investigation of the linked claimants"),
    CheckId.CONSISTENCY_MISMATCH: ("request_documents", "Ask for documents that resolve the mismatch"),
    CheckId.MISSING_EVIDENCE: ("request_documents", "Ask for the missing documents"),
}


def _original(record: MasterRecord, finding: Finding) -> Tuple[float, str]:
    by_id = {line.line_id: line.amount for line in record.lines}
    touched = [by_id[line_id] for line_id in finding.line_ids if line_id in by_id]
    if touched:
        return round(sum(touched), 2), "lines"
    if finding.check_id in SETTLEMENT_CHECKS and record.claim.proposed_settlement is not None:
        return round(record.claim.proposed_settlement, 2), "proposed_settlement"
    return round(record.claim.requested_amount, 2), "requested"


def attach_corrections(record: MasterRecord, findings: List[Finding]) -> List[Finding]:
    """Sets `correction` on every finding (in place) and returns the list."""
    cur = record.claim.currency
    for finding in findings:
        action, label = ACTIONS.get(finding.check_id, ("request_documents", "Review the finding"))
        original, basis = _original(record=record, finding=finding)
        corrected = round(max(0.0, original - finding.amount), 2)
        finding.correction = Correction(
            action=action, label=label, original_amount=original, corrected_amount=corrected,
            delta=round(original - corrected, 2), basis=basis,
            calculation=f"{money(original, cur)} - {money(finding.amount, cur)} = {money(corrected, cur)}",
            rule_id=finding.rule_id, rule_text=finding.rule_text,
            clause_id=finding.clause.clause_id if finding.clause else None)
    return findings
