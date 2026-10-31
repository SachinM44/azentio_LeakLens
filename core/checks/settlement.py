"""Deterministic settlement: invoice lines → minus the deductions the findings justify → deductible → copay →
annual-limit cap → payable; then the handler's proposed figure is compared with it."""
from __future__ import annotations

from typing import Dict, List

from core.checks._common import make_finding, money
from core.schemas.finding import AmountKind, CheckCategory, CheckId, Evidence, Finding
from core.schemas.master import ClaimType, MasterRecord
from core.schemas.settlement import Deduction, Settlement

# Findings that describe the settlement itself; they are never deducted again.
SETTLEMENT_CHECKS = {CheckId.COPAY_NOT_APPLIED, CheckId.DEDUCTIBLE_NOT_APPLIED, CheckId.SETTLEMENT_MISMATCH}


def copay_pct_for(record: MasterRecord) -> float:
    policy = record.policy
    if policy is None:
        return 0.0
    kind = record.claim.claim_type
    if kind in (ClaimType.INPATIENT, ClaimType.DAYCARE):
        return policy.copay.inpatient_pct
    if kind == ClaimType.PHARMACY:
        return policy.copay.pharmacy_pct
    if kind == ClaimType.OUTPATIENT:
        return policy.copay.outpatient_pct
    return 0.0


def _used_in_year(record: MasterRecord) -> float:
    from core.checks.policy_rules import used_in_policy_year
    return used_in_policy_year(record)


def recalculate(record: MasterRecord, findings: List[Finding]) -> Settlement:
    claim, policy, cur = record.claim, record.policy, record.claim.currency
    steps: List[str] = []
    lines_total = round(sum(l.amount for l in record.lines), 2) if record.lines else round(claim.requested_amount, 2)
    steps.append(f"Invoice lines total {money(lines_total, cur)}" + ("" if record.lines else " (no lines; requested amount used)"))

    # Deductions: one finding may not take more than the lines it points at; claim-level findings take from the rest.
    remaining: Dict[str, float] = {l.line_id: max(0.0, l.amount) for l in record.lines}
    pool = lines_total
    deductions: List[Deduction] = []
    for f in findings:
        if f.check_id in SETTLEMENT_CHECKS or f.effective_amount <= 0:
            continue
        wanted = f.effective_amount
        if f.line_ids:
            capacity = sum(remaining.get(l, 0.0) for l in f.line_ids)
            applied = round(min(wanted, capacity, pool), 2)
            left = applied
            for l in f.line_ids:
                take = min(remaining.get(l, 0.0), left)
                remaining[l] = remaining.get(l, 0.0) - take
                left -= take
        else:
            applied = round(min(wanted, pool), 2)
            if applied > 0:  # a claim-level deduction empties the lines proportionally
                scale = 1 - applied / pool if pool else 0
                for l in remaining:
                    remaining[l] = round(remaining[l] * scale, 2)
        if applied <= 0:
            continue
        pool = round(pool - applied, 2)
        deductions.append(Deduction(finding_id=f.finding_id, check_id=f.check_id.value, amount=applied, reason=f.reason[:120]))
        steps.append(f"- {money(applied, cur)} {f.check_id.value} ({f.rule_id})")
    after = round(lines_total - sum(d.amount for d in deductions), 2)
    steps.append(f"After deductions {money(after, cur)}")

    deductible = 0.0
    if policy and policy.deductible.amount > 0 and after > 0:
        deductible = round(min(after, policy.deductible.amount), 2)
        steps.append(f"- deductible {money(deductible, cur)} ({policy.deductible.basis.replace('_', ' ')})")
    copay_pct = copay_pct_for(record)
    copay_amount = round((after - deductible) * copay_pct / 100.0, 2) if copay_pct else 0.0
    if copay_pct:
        steps.append(f"- copay {copay_pct:g}% of {money(after - deductible, cur)} = {money(copay_amount, cur)}")
    payable = round(after - deductible - copay_amount, 2)

    cap = 0.0
    if policy:
        used = _used_in_year(record)
        left = max(0.0, policy.annual_limit - used)
        if payable > left:
            cap = round(payable - left, 2)
            payable = round(left, 2)
            steps.append(f"- annual limit cap {money(cap, cur)} (limit {money(policy.annual_limit, cur)}, already paid {money(used, cur)})")
    steps.append(f"Payable by insurer {money(payable, cur)}")
    patient = round(lines_total - payable, 2)
    difference = round(claim.proposed_settlement - payable, 2) if claim.proposed_settlement is not None else None
    if difference is not None:
        steps.append(f"Proposed {money(claim.proposed_settlement, cur)} vs recalculated {money(payable, cur)}: "
                     f"{'overpayment ' if difference > 0 else 'difference '}{money(abs(difference), cur)}")
    return Settlement(claim_id=claim.claim_id, currency=cur, requested_amount=claim.requested_amount, lines_total=lines_total,
                      deductions=deductions, after_deductions=after, deductible_amount=deductible, copay_pct=copay_pct,
                      copay_amount=copay_amount, benefit_cap_applied=cap, payable=payable, patient_pays=patient,
                      proposed_settlement=claim.proposed_settlement, difference=difference, steps=steps)


def settlement_findings(record: MasterRecord, settlement: Settlement) -> List[Finding]:
    """Where the handler's proposed figure is above the recalculation, name the step that was skipped."""
    claim, cur = record.claim, record.claim.currency
    if settlement.difference is None or settlement.difference <= 1.0:
        return []
    diff = settlement.difference
    evidence = [Evidence(source="claim", ref=claim.claim_id, quote=f"proposed settlement {money(claim.proposed_settlement, cur)}"),
                Evidence(source="config", ref="settlement", quote=" | ".join(settlement.steps))]
    out: List[Finding] = []
    explained = 0.0
    if settlement.copay_amount > 0 and diff >= settlement.copay_amount - 1.0:
        out.append(make_finding(
            record, CheckId.COPAY_NOT_APPLIED, amount=settlement.copay_amount, kind=AmountKind.CALCULATED, rule_id="SETL-COPAY",
            rule_text=f"A {settlement.copay_pct:g}% copay applies to this claim type.",
            calculation=f"{settlement.copay_pct:g}% x {money(settlement.after_deductions - settlement.deductible_amount, cur)} = {money(settlement.copay_amount, cur)}",
            reason="The proposed settlement does not deduct the copay.", evidence=evidence))
        explained += settlement.copay_amount
    if settlement.deductible_amount > 0 and diff - explained >= settlement.deductible_amount - 1.0:
        out.append(make_finding(
            record, CheckId.DEDUCTIBLE_NOT_APPLIED, amount=settlement.deductible_amount, kind=AmountKind.CALCULATED,
            rule_id="SETL-DEDUCTIBLE", rule_text="The policy deductible is taken off before payment.",
            calculation=f"deductible {money(settlement.deductible_amount, cur)} not deducted from the proposed figure",
            reason="The proposed settlement does not deduct the deductible.", evidence=evidence))
        explained += settlement.deductible_amount
    rest = round(diff - explained, 2)
    if rest > 1.0:
        out.append(make_finding(
            record, CheckId.SETTLEMENT_MISMATCH, amount=rest, kind=AmountKind.CALCULATED, rule_id="SETL-RECALC",
            rule_text="The settlement is recomputed from the invoice lines and the policy rules.",
            calculation=f"proposed {money(claim.proposed_settlement, cur)} - recalculated {money(settlement.payable, cur)}"
                        + (f" - already explained {money(explained, cur)}" if explained else "") + f" = {money(rest, cur)}",
            reason="The proposed settlement is higher than the rules allow.", evidence=evidence))
    return out
