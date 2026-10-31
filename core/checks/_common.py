"""Shared helpers for the checks: text normalisation, fuzzy matching, money formatting, the finding factory."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Iterable, List, Optional, Sequence

from rapidfuzz import fuzz

from core.schemas.finding import (CHECK_CATEGORY, AmountKind, CheckId, ClauseRef, Evidence, Finding, Severity)
from core.schemas.master import Claim, InvoiceLine, MasterRecord, ProductConfig

_NOISE = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
_STOP = {"the", "of", "and", "for", "charges", "charge", "fee", "fees", "per", "x", "nos", "no"}


def norm(text: Optional[str]) -> str:
    """Lower-case, punctuation stripped, filler words removed: 'Complete Blood Count (CBC)' -> 'complete blood count cbc'."""
    words = _SPACES.sub(" ", _NOISE.sub(" ", (text or "").lower())).split()
    return " ".join(w for w in words if w not in _STOP)


def similar(a: Optional[str], b: Optional[str]) -> float:
    """0..1 token-set similarity; word order and repeats do not matter."""
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(norm(a), norm(b)) / 100.0


def matches_any(text: Optional[str], keywords: Iterable[str], threshold: float = 0.88) -> Optional[str]:
    """The keyword the text contains or closely resembles, else None."""
    n = norm(text)
    if not n:
        return None
    for kw in keywords:
        k = norm(kw)
        if not k:
            continue
        # Whole words only: "aesthetic" must not match "anaesthetist"; token_set tolerates word order and extras.
        if f" {k} " in f" {n} " or (len(k) >= 5 and fuzz.token_set_ratio(k, n) / 100.0 >= threshold):
            return kw
    return None


def code_in(line: InvoiceLine, codes: Sequence[str]) -> bool:
    return bool(line.code) and line.code.strip().upper() in {c.strip().upper() for c in codes if c}


def money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def line_quote(line: InvoiceLine, currency: str) -> str:
    code = f"[{line.code}] " if line.code else ""
    when = f" on {line.service_date.isoformat()}" if line.service_date else ""
    return f"{line.invoice_no} #{line.serial_no}: {code}{line.description} x{line.quantity:g} = {money(line.amount, currency)}{when}"


def line_evidence(line: InvoiceLine, currency: str) -> Evidence:
    return Evidence(source="invoice_line", ref=line.line_id, quote=line_quote(line, currency))


def unit_price(line: InvoiceLine) -> float:
    if line.unit_price is not None:
        return float(line.unit_price)
    return float(line.amount) / line.quantity if line.quantity else float(line.amount)


def stay_days(claim: Claim) -> Optional[int]:
    if claim.admission_date and claim.discharge_date:
        return max(1, (claim.discharge_date - claim.admission_date).days)
    return None


def within(d: Optional[date], start: Optional[date], end: Optional[date], slack_days: int = 0) -> bool:
    if d is None or start is None or end is None:
        return True
    return start - timedelta(days=slack_days) <= d <= end + timedelta(days=slack_days)


def severity_for(amount: float, record: MasterRecord, kind: AmountKind) -> Severity:
    """High when the amount is large against the claim; low when no money rides on the finding."""
    requested = max(record.claim.requested_amount, 1.0)
    big = 10_000.0 if record.claim.currency == "INR" else 1_000.0
    if amount <= 0:
        return Severity.LOW if kind == AmountKind.CALCULATED else Severity.MEDIUM
    if amount >= big or amount / requested >= 0.10:
        return Severity.HIGH
    return Severity.MEDIUM


def make_finding(record: MasterRecord, check: CheckId, *, amount: float, kind: AmountKind, rule_id: str, rule_text: str,
                 calculation: str = "", reason: str = "", lines: Sequence[InvoiceLine] = (),
                 evidence: Sequence[Evidence] = (), clause: Optional[ClauseRef] = None,
                 related_claim_ids: Sequence[str] = (), severity: Optional[Severity] = None) -> Finding:
    """One finding; the runner numbers the ids afterwards."""
    amount = round(max(0.0, float(amount)), 2)
    return Finding(finding_id="", claim_id=record.claim.claim_id, check_id=check, category=CHECK_CATEGORY[check],
                   severity=severity or severity_for(amount, record, kind), amount=amount, amount_kind=kind,
                   currency=record.claim.currency, rule_id=rule_id, rule_text=rule_text, calculation=calculation,
                   reason=reason, line_ids=[l.line_id for l in lines],
                   evidence=list(evidence) or [line_evidence(l, record.claim.currency) for l in lines],
                   clause=clause, related_claim_ids=list(related_claim_ids))


def product_for(record: MasterRecord) -> ProductConfig:
    if record.product:
        return record.product
    return ProductConfig(product_id=record.claim.product_id, name=record.claim.product_id, insurer="", market="",
                         currency=record.claim.currency)


_ICU_RE = re.compile(r"\b(icu|iccu|hdu|intensive care|critical care)\b", re.I)
_ROOM_RE = re.compile(r"\b(room|bed|ward|accommodation)\b", re.I)
# Rooms that are procedure areas, not accommodation, plus bed-related consumables.
_NOT_ROOM_RE = re.compile(r"\b(bed ?pan|companion bed|attendant bed|bedside|bed side|ward boy|labou?r room|delivery room|"
                          r"operating room|operation room|operation theat|ot room|recovery room|emergency room|procedure room|"
                          r"treatment room|consult(ation|ing)? room|dressing room|dialysis room)\b", re.I)
_PER_DAY_RE = re.compile(r"\b(per day|nursing|daily|day care)\b", re.I)


def is_icu_line(line: InvoiceLine) -> bool:
    if line.category and line.category.value == "icu":
        return True
    return bool(_ICU_RE.search(line.description or ""))


def is_room_line(line: InvoiceLine) -> bool:
    if line.category and line.category.value == "room":
        return True
    desc = line.description or ""
    return bool(_ROOM_RE.search(desc)) and not _NOT_ROOM_RE.search(desc) and not is_icu_line(line)


def per_day_line(line: InvoiceLine) -> bool:
    return is_room_line(line) or is_icu_line(line) or bool(_PER_DAY_RE.search(line.description or ""))


def positive_lines(record: MasterRecord) -> List[InvoiceLine]:
    return [l for l in record.lines if l.amount > 0]
