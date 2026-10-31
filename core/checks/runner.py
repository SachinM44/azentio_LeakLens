"""Runs every check over one master record, in an order that lets the settlement cap overlapping deductions,
numbers the findings, and adds the settlement-mismatch findings last."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from core.checks import duplicates, patterns, policy_rules
from core.checks.corrections import attach_corrections
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
    claim_level = duplicates.check_duplicate_claim(record, history_index, other_claims)
    findings += claim_level
    findings += duplicates.check_duplicate_lines(record)
    covered = {cid for f in claim_level for cid in f.related_claim_ids}
    # A claim already flagged as a (near-)duplicate of claim X does not also get its lines flagged against X.
    findings += [f for f in duplicates.check_cross_claim_lines(record) if not set(f.related_claim_ids) & covered]
    findings += policy_rules.check_benefit_limit(record)
    findings += patterns.check_consistency(record)
    findings += patterns.check_provider_outlier(record, peer_lines)
    findings += patterns.check_related_party(record, other_claims)
    findings = number(findings, record.claim.claim_id)
    settlement = recalculate(record=record, findings=findings)
    extra = number(settlement_findings(record, settlement), record.claim.claim_id)
    return attach_corrections(record=record, findings=findings + extra)
