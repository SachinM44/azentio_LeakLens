"""Runs every check over one master record, in an order that lets the settlement cap overlapping deductions,
numbers the findings, and adds the settlement-mismatch findings last."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from core.checks import duplicates, patterns, policy_rules
from core.checks.settlement import recalculate, settlement_findings
from core.schemas.finding import Finding
from core.schemas.master import Claim, HistoryRecord, InvoiceLine, MasterRecord


def number(findings: List[Finding], claim_id: str) -> List[Finding]:
    counts: Counter = Counter()
    seen = set()
    out: List[Finding] = []
    for f in findings:
        key = (f.check_id, tuple(f.line_ids), tuple(f.related_claim_ids), f.rule_id)
        if key in seen:
            continue
        seen.add(key)
        counts[f.check_id] += 1
        f.finding_id = f"{claim_id}:{f.check_id.value}:{counts[f.check_id]}"
        out.append(f)
    return out


def run_all(*, record: MasterRecord, history_index: Dict[str, HistoryRecord], other_claims: List[Claim],
            peer_lines: List[InvoiceLine]) -> List[Finding]:
    findings: List[Finding] = []
    # Claim-level rules first (they can take the whole claim), then line rules, then duplicates and patterns.
    findings += policy_rules.check_missing_evidence(record)
    findings += policy_rules.check_coverage(record)
    if not findings or all(f.amount == 0 for f in findings):
        findings += policy_rules.check_waiting_periods(record)
        findings += policy_rules.check_network(record)
    findings += policy_rules.check_exclusions(record)
    findings += policy_rules.check_non_payable(record)
    findings += policy_rules.check_room_limits(record)
    findings += policy_rules.check_sublimits(record)
    findings += policy_rules.check_quantity_vs_stay(record)
    findings += policy_rules.check_dates(record)
    findings += policy_rules.check_arithmetic(record)
    findings += duplicates.check_duplicate_claim(record, history_index, other_claims)
    findings += duplicates.check_duplicate_lines(record)
    findings += duplicates.check_cross_claim_lines(record)
    findings += policy_rules.check_benefit_limit(record)
    findings += patterns.check_consistency(record)
    findings += patterns.check_provider_outlier(record, peer_lines)
    findings += patterns.check_related_party(record, other_claims)
    findings = number(findings, record.claim.claim_id)
    settlement = recalculate(record=record, findings=findings)
    extra = number(settlement_findings(record, settlement), record.claim.claim_id)
    return findings + extra
