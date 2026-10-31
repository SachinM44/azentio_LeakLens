"""Patterns for human review (never an automatic verdict): documents that disagree with the claim, a provider
whose prices sit far above its peers, and claimants who share contact or bank details."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Dict, List, Tuple

from core.checks._common import make_finding, money, norm, positive_lines, product_for, similar, unit_price
from core.schemas.finding import AmountKind, CheckId, Evidence, Finding, Severity
from core.schemas.master import Claim, InvoiceLine, MasterRecord


def _item_key(line: InvoiceLine) -> str:
    return line.code.strip().upper() if line.code else norm(line.description)


def check_consistency(record: MasterRecord) -> List[Finding]:
    """The facts printed on the documents must agree with the claim record."""
    facts = record.document_facts
    if not facts:
        return []
    claim = record.claim
    conflicts: List[Tuple[str, str, str]] = []
    name = facts.get("claimant_name")
    if name and claim.claimant_name and similar(name, claim.claimant_name) < 0.8:
        conflicts.append(("claimant name", claim.claimant_name, name))
    pol = facts.get("policy_number")
    if pol and pol.strip().upper() != claim.policy_number.strip().upper():
        conflicts.append(("policy number", claim.policy_number, pol))
    prov = facts.get("provider_name")
    if prov and claim.provider_name and similar(prov, claim.provider_name) < 0.7:
        conflicts.append(("provider", claim.provider_name, prov))
    for key, value in (("admission_date", claim.admission_date), ("discharge_date", claim.discharge_date)):
        printed = facts.get(key)
        if printed and value and printed[:10] != value.isoformat():
            conflicts.append((key.replace("_", " "), value.isoformat(), printed[:10]))
    inv = facts.get("invoice_no")
    if inv and claim.invoice_numbers and inv.strip().upper() not in {i.strip().upper() for i in claim.invoice_numbers}:
        conflicts.append(("invoice number", ", ".join(claim.invoice_numbers), inv))
    if not conflicts:
        return []
    high = any(c[0] in ("claimant name", "policy number") for c in conflicts)
    return [make_finding(
        record, CheckId.CONSISTENCY_MISMATCH, amount=claim.requested_amount if high else 0.0, kind=AmountKind.SUSPECTED,
        rule_id="CONS-01", rule_text="The claim record and its documents must describe the same patient, policy and episode.",
        calculation="; ".join(f"{f}: claim says '{a}', document says '{b}'" for f, a, b in conflicts),
        reason=("The attached document may belong to another claim or member." if high
                else "The documents and the claim record disagree on the episode details."),
        evidence=[Evidence(source="document", ref=f, quote=f"claim '{a}' vs document '{b}'") for f, a, b in conflicts],
        severity=Severity.HIGH if high else Severity.MEDIUM)]


def check_provider_outlier(record: MasterRecord, peer_lines: List[InvoiceLine]) -> List[Finding]:
    """Unit prices far above what other providers charge for the same item."""
    claim = record.claim
    product = product_for(record)
    peers: Dict[str, List[float]] = defaultdict(list)
    for line in peer_lines:
        if line.provider_id and line.provider_id != claim.provider_id and line.amount > 0 and line.quantity:
            peers[_item_key(line)].append(unit_price(line))
    findings: List[Finding] = []
    for line in positive_lines(record):
        prices = peers.get(_item_key(line), [])
        if len(prices) < 5:
            continue
        mean, median = statistics.fmean(prices), statistics.median(prices)
        std = statistics.pstdev(prices)
        rate = unit_price(line)
        z = (rate - mean) / std if std > 0 else (float("inf") if rate > mean * 1.3 else 0.0)
        if z >= product.provider_outlier_zscore and rate > median * 1.3:
            excess = round((rate - median) * (line.quantity or 1), 2)
            findings.append(make_finding(
                record, CheckId.PROVIDER_PRICE_OUTLIER, amount=excess, kind=AmountKind.SUSPECTED, rule_id="PROV-01",
                rule_text="A unit price far above peer providers for the same item is reviewed before payment.",
                calculation=f"{money(rate, claim.currency)} vs peer median {money(median, claim.currency)} over {len(prices)} lines "
                            f"(z = {z:.1f}); (rate - median) x {line.quantity:g} = {money(excess, claim.currency)} suspected",
                reason=f"'{line.description}' is priced well above other providers.", lines=[line]))
    return findings


def _masked(value: str) -> str:
    v = value.strip()
    return ("*" * max(0, len(v) - 4)) + v[-4:] if len(v) > 4 else v


def check_related_party(record: MasterRecord, other_claims: List[Claim]) -> List[Finding]:
    """Different claimants at the same provider who share a phone, bank account or address."""
    claim = record.claim
    keys = {"phone": claim.contact_phone, "bank account": claim.bank_account, "address": claim.address}
    keys = {k: norm(v) for k, v in keys.items() if v}
    if not keys:
        return []
    shared: Dict[str, List[str]] = defaultdict(list)
    for other in other_claims:
        if other.claim_id == claim.claim_id or other.claimant_id == claim.claimant_id:
            continue
        if other.provider_id != claim.provider_id:
            continue
        theirs = {"phone": other.contact_phone, "bank account": other.bank_account, "address": other.address}
        for k, v in theirs.items():
            if v and k in keys and norm(v) == keys[k]:
                shared[k].append(other.claim_id)
    if not shared:
        return []
    related = sorted({cid for ids in shared.values() for cid in ids})
    return [make_finding(
        record, CheckId.RELATED_PARTY_PATTERN, amount=claim.requested_amount, kind=AmountKind.SUSPECTED, rule_id="PROV-02",
        rule_text="Claims from different members sharing contact or bank details at one provider are reviewed together.",
        calculation="; ".join(f"{k} shared with {len(ids)} other claimant(s): {', '.join(ids)}" for k, ids in shared.items()),
        reason=f"{len(related)} other claim(s) at {claim.provider_name or claim.provider_id} share this claimant's "
               + ", ".join(shared.keys()) + ".",
        evidence=[Evidence(source="claim", ref=cid, quote=f"shares {k} ({_masked(getattr(claim, {'phone': 'contact_phone', 'bank account': 'bank_account', 'address': 'address'}[k]) or '')})")
                  for k, ids in shared.items() for cid in ids],
        related_claim_ids=related, severity=Severity.MEDIUM)]
