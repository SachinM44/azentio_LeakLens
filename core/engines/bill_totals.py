"""Bill footer totals (grand total, discount, net payable) and discount-row detection."""
from __future__ import annotations

from core.engines.bill_utils import bill_line_looks_like_tax, resolve_bill_line_total_amount

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import re


_BILL_FOOTER_FIELD_IDS = frozenset(
    {"total_tax", "total_amount", "grand_total", "net_payable", "total_discount"}
)


_BILL_FOOTER_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "grand_total": ("grand_total", "grand total", "gross total"),
    "total_amount": ("total_amount", "total amount", "bill amount", "total due"),
    "net_payable": (
        "net_payable",
        "net payable",
        "amount payable",
        "amount_payable",
        "net amount",
        "net bill amount",
        "final bill amount",
        "final amount",
        "amount due",
    ),
}


def _normalize_bill_field_key(key: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (key or "").strip().lower())


def resolve_bill_footer_field_id(label: str) -> Optional[str]:
    """Map a digitized field label to a canonical footer field_id, if recognized."""
    norm = _normalize_bill_field_key(label)
    if not norm:
        return None
    for canonical, aliases in _BILL_FOOTER_FIELD_ALIASES.items():
        candidates = {_normalize_bill_field_key(canonical), *(_normalize_bill_field_key(a) for a in aliases)}
        if norm in candidates:
            return canonical
    return None


def _field_value_nonempty(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text not in {"", "na", "n/a", "null", "none", "-"}


def merge_bill_document_data_from_batches(
    batch_results: List[Any],
) -> Dict[str, Any]:
    """
    Merge document_data.fields from per-page bill digitization batches.

    Footer totals (grand_total, net_payable, etc.) are extracted in document_data
    per batch; without merging, multi-page bill digitization drops them.
    """
    by_field_id: Dict[str, Dict[str, Any]] = {}
    for batch_result in batch_results:
        if isinstance(batch_result, Exception):
            continue
        if not isinstance(batch_result, dict) or not batch_result.get("success", False):
            continue
        doc_data = batch_result.get("document_data") or {}
        if not isinstance(doc_data, dict):
            continue
        for field in doc_data.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_id = str(field.get("field_id") or "").strip()
            if not field_id:
                continue
            incoming = {
                "field_id": field_id,
                "field_alias": field.get("field_alias") or field_id,
                "value": field.get("value"),
            }
            existing = by_field_id.get(field_id)
            if not existing:
                by_field_id[field_id] = incoming
                continue
            if _field_value_nonempty(incoming.get("value")) and not _field_value_nonempty(
                existing.get("value")
            ):
                by_field_id[field_id] = incoming
            elif (
                field_id in _BILL_FOOTER_FIELD_IDS
                and _field_value_nonempty(incoming.get("value"))
                and _field_value_nonempty(existing.get("value"))
            ):
                by_field_id[field_id] = incoming
    return {"fields": list(by_field_id.values())}


_DISCOUNT_NAME_RE = re.compile(
    r"\b(discount|concession|waiver|rebate|round[- ]?off|write[- ]?off|"
    r"less\s*:|scheme\s+discount|insurance\s+discount)\b",
    re.IGNORECASE,
)


def bill_line_looks_like_discount(item: Dict[str, Any]) -> bool:
    """True when the row is a discount, concession, or round-off line."""
    name = (
        item.get("item_name")
        or item.get("service_name")
        or item.get("description")
        or ""
    )
    # Name evidence ONLY: a negative amount alone is NOT discount evidence —
    # item-level returns/reversals (drug returns with qty < 0) are negative
    # charge rows, and counting them as discount fabricated a total_discount
    # that no bill printed (Lucknow: 1,208.38 of pharmacy returns).
    return bool(_DISCOUNT_NAME_RE.search(str(name)))


def _round_currency(value: float) -> float:
    return round(value, 2)


def compute_bill_summary_totals(
    bill_items: List[Dict[str, Any]],
) -> Dict[str, float]:
    """
    Derive document-level totals from bill line items when not printed on the bill.

    Uses the same sign convention as stored on each line (discounts may be negative).
    """
    net_payable = 0.0
    total_tax = 0.0
    total_discount = 0.0
    charge_subtotal = 0.0

    for item in bill_items:
        if not isinstance(item, dict):
            continue
        amount = resolve_bill_line_total_amount(item)
        if amount is None:
            continue
        net_payable += amount
        if bill_line_looks_like_tax(item):
            total_tax += amount
        elif bill_line_looks_like_discount(item):
            total_discount += abs(amount)
        else:
            charge_subtotal += amount

    grand_total = charge_subtotal + total_tax
    if grand_total == 0.0 and net_payable != 0.0:
        grand_total = net_payable

    return {
        "net_payable": _round_currency(net_payable),
        "total_tax": _round_currency(total_tax),
        "total_discount": _round_currency(total_discount),
        "grand_total": _round_currency(grand_total),
    }
