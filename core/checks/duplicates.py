"""Duplicate detection: the same invoice or incident submitted twice, the same charge repeated within or across
claims, near-duplicates with small differences (for review), and legitimate repeat services left alone."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from core.checks._common import (code_in, line_evidence, make_finding, money, norm, positive_lines, product_for,
                                 similar)
from core.schemas.finding import AmountKind, CheckId, Evidence, Finding, Severity
from core.schemas.master import Claim, HistoryRecord, InvoiceLine, MasterRecord

SAME_ITEM_SIMILARITY = 0.90
EXACT_AMOUNT_TOLERANCE_PCT = 0.5


def same_item(a: InvoiceLine, b: InvoiceLine) -> bool:
    """Same code when both have one; otherwise the descriptions must be near-identical."""
    if a.code and b.code:
        return a.code.strip().upper() == b.code.strip().upper()
    return similar(a.description, b.description) >= SAME_ITEM_SIMILARITY


def amounts_close(a: float, b: float, pct: float) -> bool:
    return abs(a - b) <= max(0.5, abs(b) * pct / 100.0)


def days_apart(a, b) -> Optional[int]:
    if a is None or b is None:
        return None
    return abs((a - b).days)


def _utc(moment: datetime) -> datetime:
    """Submission times arrive with and without a timezone (uploads vs the portal); compare them as UTC."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _later(claim: Claim, other: Claim) -> bool:
    """True when `claim` is the later submission (the one that counts as the duplicate)."""
    if claim.submitted_at and other.submitted_at and _utc(claim.submitted_at) != _utc(other.submitted_at):
        return _utc(claim.submitted_at) > _utc(other.submitted_at)
    return claim.claim_id > other.claim_id


def check_duplicate_claim(record: MasterRecord, history_index: Dict[str, HistoryRecord],
                          other_claims: List[Claim]) -> List[Finding]:
    claim = record.claim
    product = product_for(record)
    findings: List[Finding] = []
    mine = {i.strip().upper() for i in claim.invoice_numbers if i}

    for h in history_index.values():
        if h.claimant_id != claim.claimant_id and h.policy_number != claim.policy_number:
            continue
        shared = sorted(mine & {i.strip().upper() for i in h.invoice_numbers if i})
        if shared:
            paid = h.paid_amount if h.paid_amount > 0 else h.approved_amount
            amount = min(claim.requested_amount, paid) if paid > 0 else claim.requested_amount
            findings.append(make_finding(
                record, CheckId.DUPLICATE_CLAIM, amount=amount, kind=AmountKind.CALCULATED, rule_id="DUP-CLAIM-01",
                rule_text="An invoice already settled under an earlier claim is not payable again.",
                calculation=f"invoice {', '.join(shared)} paid {money(paid, claim.currency)} under {h.claim_id}"
                            f"{' on ' + h.paid_on.isoformat() if h.paid_on else ''}; duplicate = min(requested, paid)",
                reason=f"Invoice {', '.join(shared)} was already paid under claim {h.claim_id}.",
                evidence=[Evidence(source="history", ref=h.claim_id,
                                   quote=f"paid {money(paid, claim.currency)} for invoices {', '.join(h.invoice_numbers)}")],
                related_claim_ids=[h.claim_id], severity=Severity.HIGH))
            continue
        gap = days_apart(claim.incident_date, h.incident_date)
        if (h.provider_id == claim.provider_id and gap is not None and gap <= product.near_duplicate_days
                and amounts_close(claim.requested_amount, h.requested_amount, product.near_duplicate_amount_tolerance_pct)):
            findings.append(make_finding(
                record, CheckId.NEAR_DUPLICATE, amount=claim.requested_amount, kind=AmountKind.SUSPECTED,
                rule_id="DUP-CLAIM-02",
                rule_text="A claim at the same provider within a few days for almost the same amount needs a human look.",
                calculation=f"{gap} day(s) apart, {money(claim.requested_amount, claim.currency)} vs "
                            f"{money(h.requested_amount, claim.currency)}; invoice numbers differ",
                reason=f"Looks like earlier claim {h.claim_id} resubmitted with new references.",
                evidence=[Evidence(source="history", ref=h.claim_id,
                                   quote=f"{h.incident_date.isoformat()} {h.provider_id} requested "
                                         f"{money(h.requested_amount, claim.currency)}")],
                related_claim_ids=[h.claim_id]))

    for other in other_claims:
        if other.claim_id == claim.claim_id or not _later(claim, other):
            continue
        if other.claimant_id != claim.claimant_id and other.policy_number != claim.policy_number:
            continue
        shared = sorted(mine & {i.strip().upper() for i in other.invoice_numbers if i})
        if shared:
            findings.append(make_finding(
                record, CheckId.DUPLICATE_CLAIM, amount=claim.requested_amount, kind=AmountKind.CALCULATED,
                rule_id="DUP-CLAIM-01", rule_text="The same invoice cannot be claimed twice.",
                calculation=f"invoice {', '.join(shared)} also on claim {other.claim_id}; duplicate = requested amount",
                reason=f"Invoice {', '.join(shared)} is also attached to claim {other.claim_id}.",
                evidence=[Evidence(source="claim", ref=other.claim_id,
                                   quote=f"invoices {', '.join(other.invoice_numbers)} requested "
                                         f"{money(other.requested_amount, claim.currency)}")],
                related_claim_ids=[other.claim_id], severity=Severity.HIGH))
            continue
        gap = days_apart(claim.incident_date, other.incident_date)
        if (other.provider_id == claim.provider_id and gap is not None and gap <= product.near_duplicate_days
                and amounts_close(claim.requested_amount, other.requested_amount, product.near_duplicate_amount_tolerance_pct)):
            findings.append(make_finding(
                record, CheckId.NEAR_DUPLICATE, amount=claim.requested_amount, kind=AmountKind.SUSPECTED,
                rule_id="DUP-CLAIM-02",
                rule_text="A claim at the same provider within a few days for almost the same amount needs a human look.",
                calculation=f"{gap} day(s) apart, {money(claim.requested_amount, claim.currency)} vs "
                            f"{money(other.requested_amount, claim.currency)}; invoice numbers differ",
                reason=f"Looks like claim {other.claim_id} resubmitted with new references.",
                evidence=[Evidence(source="claim", ref=other.claim_id,
                                   quote=f"{other.incident_date.isoformat()} {other.provider_id} requested "
                                         f"{money(other.requested_amount, claim.currency)}")],
                related_claim_ids=[other.claim_id]))
    return findings


def check_duplicate_lines(record: MasterRecord) -> List[Finding]:
    """Within one claim: an exact repeat is leakage; a near repeat is for review; a repeatable service on another
    date is legitimate."""
    product = product_for(record)
    repeat_codes = product.repeatable_service_codes
    lines = positive_lines(record)
    findings: List[Finding] = []
    flagged: set = set()
    for i, a in enumerate(lines):
        if a.line_id in flagged:
            continue
        for b in lines[:i]:
            if not same_item(a, b):
                continue
            gap = days_apart(a.service_date, b.service_date)
            same_day = gap == 0 or gap is None
            repeatable = code_in(a, repeat_codes)
            if same_day and amounts_close(a.amount, b.amount, EXACT_AMOUNT_TOLERANCE_PCT):
                findings.append(make_finding(
                    record, CheckId.DUPLICATE_LINE, amount=a.amount, kind=AmountKind.CALCULATED, rule_id="DUP-LINE-01",
                    rule_text="The same charge on the same day appears twice on the invoice; the second is not payable.",
                    calculation=f"line #{a.serial_no} repeats line #{b.serial_no}: {money(a.amount, record.claim.currency)} x 1",
                    reason=f"'{a.description}' is billed twice for the same date.", lines=[a, b]))
                flagged.add(a.line_id)
                break
            if not same_day:
                continue  # the same test or session on another date of the stay is a repeat service, not a duplicate
            if amounts_close(a.amount, b.amount, product.near_duplicate_amount_tolerance_pct):
                findings.append(make_finding(
                    record, CheckId.NEAR_DUPLICATE, amount=a.amount, kind=AmountKind.SUSPECTED, rule_id="DUP-LINE-02",
                    rule_text="The same service a few days apart for almost the same amount needs a human look.",
                    calculation=f"same day; {money(a.amount, record.claim.currency)} vs {money(b.amount, record.claim.currency)}",
                    reason=f"'{a.description}' appears twice on the same day with a small change in amount.", lines=[a, b]))
                flagged.add(a.line_id)
                break
    return findings


def check_cross_claim_lines(record: MasterRecord) -> List[Finding]:
    """A charge already paid on an earlier claim of the same member (record.history carries that member's claims)."""
    product = product_for(record)
    findings: List[Finding] = []
    history_lines = [(h, l) for h in record.history if h.claimant_id == record.claim.claimant_id for l in h.lines]
    if not history_lines:
        return findings
    for a in positive_lines(record):
        for h, b in history_lines:
            if not same_item(a, b):
                continue
            gap = days_apart(a.service_date, b.service_date)
            if gap == 0 and amounts_close(a.amount, b.amount, EXACT_AMOUNT_TOLERANCE_PCT):
                findings.append(make_finding(
                    record, CheckId.CROSS_CLAIM_DUPLICATE_LINE, amount=a.amount, kind=AmountKind.CALCULATED,
                    rule_id="DUP-LINE-03", rule_text="A charge already paid under an earlier claim is not payable again.",
                    calculation=f"same item, same date, {money(a.amount, record.claim.currency)}; paid under {h.claim_id}",
                    reason=f"'{a.description}' on {a.service_date} was paid under claim {h.claim_id}.",
                    lines=[a], evidence=[line_evidence(a, record.claim.currency),
                                         Evidence(source="history", ref=f"{h.claim_id}/{b.line_id}",
                                                  quote=f"{b.description} {money(b.amount, record.claim.currency)} on {b.service_date}")],
                    related_claim_ids=[h.claim_id], severity=Severity.HIGH))
                break
            if (gap is not None and 0 < gap <= product.near_duplicate_days and not code_in(a, product.repeatable_service_codes)
                    and amounts_close(a.amount, b.amount, product.near_duplicate_amount_tolerance_pct)):
                findings.append(make_finding(
                    record, CheckId.NEAR_DUPLICATE, amount=a.amount, kind=AmountKind.SUSPECTED, rule_id="DUP-LINE-04",
                    rule_text="A charge close to one paid on an earlier claim needs a human look.",
                    calculation=f"{gap} day(s) from the paid line; {money(a.amount, record.claim.currency)} vs {money(b.amount, record.claim.currency)}",
                    reason=f"'{a.description}' resembles a line paid under claim {h.claim_id}.",
                    lines=[a], evidence=[line_evidence(a, record.claim.currency),
                                         Evidence(source="history", ref=f"{h.claim_id}/{b.line_id}",
                                                  quote=f"{b.description} {money(b.amount, record.claim.currency)} on {b.service_date}")],
                    related_claim_ids=[h.claim_id]))
                break
    return findings
