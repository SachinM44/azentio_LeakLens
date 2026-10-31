"""Section subtotal and printed-total reconciliation for extracted bill lines."""
from __future__ import annotations

from core.engines.bill_utils import exclude_category_rollup_bill_items

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import re


# A document is complete when its payable line sum is within this fraction of a
# printed footer total (or within the absolute rupee floor, whichever is larger).
BILL_COMPLETENESS_REL_TOLERANCE = 0.005


BILL_COMPLETENESS_ABS_TOLERANCE = 5.0


def _resolve_page_number(item: Dict[str, Any]) -> int:
    page_raw = item.get("page_number")
    if page_raw is not None:
        try:
            return int(page_raw)
        except (TypeError, ValueError):
            pass
    return 1


def _completeness_tolerance(anchor: float) -> float:
    return max(abs(anchor) * BILL_COMPLETENESS_REL_TOLERANCE,
               BILL_COMPLETENESS_ABS_TOLERANCE)


_SECTION_SUBTOTAL_LABEL_RE = re.compile(r"sub\s*-?\s*total", re.IGNORECASE)


_DOCUMENT_TOTAL_LABEL_RE = re.compile(
    r"^\s*(?:grand\s+total|gross\s+bill|net\s+(?:payable|amount|bill\s+amount)|"
    r"amount\s+payable|bill\s+amount|final\s+(?:bill\s+)?amount|total)\s*$",
    re.IGNORECASE,
)


def _is_printed_section_subtotal(item: Dict[str, Any]) -> bool:
    """True for a row that closes a printed BILL SECTION.

    Document-level totals (Grand Total, Net Amount) are excluded — they close
    the whole bill, not a section, and treating them as section boundaries
    would compare a section's rows against the document total.
    """
    if not isinstance(item, dict):
        return False
    name = str(item.get("item_name") or "").strip()
    if not name or _DOCUMENT_TOTAL_LABEL_RE.match(name):
        return False
    if _SECTION_SUBTOTAL_LABEL_RE.search(name):
        return True
    from core.engines.bill_utils import LINE_KIND_SECTION_SUBTOTAL

    return item.get("line_kind") == LINE_KIND_SECTION_SUBTOTAL


def _section_rows_total(rows: List[Dict[str, Any]]) -> float:
    """Sum POSITIVE charge rows only.

    Printed section subtotals are GROSS (the discount is a separate column or
    an aggregate row), so negative adjustments must not be netted off here.
    """
    from core.engines.bill_utils import resolve_bill_line_total_amount

    total = 0.0
    for row in rows:
        amount = resolve_bill_line_total_amount(row)
        if amount is not None and amount > 0:
            total += amount
    return round(total, 2)


def iter_bill_sections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split bill rows into sections delimited by printed subtotal rows.

    Bills print "<Section> Subtotal <amount>" after each section's rows, so in
    printed order every subtotal row closes the section above it.
    """
    from core.engines.bill_utils import resolve_bill_line_total_amount

    sections: List[Dict[str, Any]] = []
    start = 0
    for idx, item in enumerate(items or []):
        if not isinstance(item, dict) or not _is_printed_section_subtotal(item):
            continue
        printed = resolve_bill_line_total_amount(item)
        rows = [r for r in items[start:idx] if isinstance(r, dict)]
        if printed is not None and printed > 0 and rows:
            sections.append({
                "section": str(item.get("item_name") or "").strip(),
                "printed_subtotal": printed,
                "rows": rows,
                "start": start,
                "subtotal_index": idx,
            })
        start = idx + 1
    return sections


def find_section_subtotal_shortfalls(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sections whose charge rows sum BELOW their printed subtotal.

    A section short of its own printed total is provably missing lines, and the
    rows we do have name exactly which pages to re-read — far sharper than
    whole-document reconciliation, which only knows the grand total is short
    and re-reads everything blindly. Verified against the Reliance SOA:
    Consultation 16,100 + Laboratory 15,300 + Pharmacy 1,801.84 = exactly the
    33,201.84 document-level gap.
    """
    shortfalls: List[Dict[str, Any]] = []
    for section in iter_bill_sections(items):
        printed = section["printed_subtotal"]
        computed = _section_rows_total(section["rows"])
        difference = round(printed - computed, 2)
        if difference > _completeness_tolerance(printed):
            pages = sorted({_resolve_page_number(r) for r in section["rows"]})
            shortfalls.append({
                "section": section["section"],
                "printed_subtotal": printed,
                "computed_total": computed,
                "difference": difference,
                "pages": pages,
                "row_count": len(section["rows"]),
            })
    return shortfalls


def compute_payable_line_sum(items: List[Dict[str, Any]]) -> float:
    """Sum of charge-line totals excluding subtotals/adjustments/payment rows."""
    payable = exclude_category_rollup_bill_items(list(items))
    total = 0.0
    for item in payable:
        try:
            total += float(item.get("total_amount") or 0.0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def bill_lines_reconcile_to_printed_total(
    items: List[Dict[str, Any]],
    printed_totals: Optional[Dict[str, float]],
) -> Optional[float]:
    """Return the printed footer anchor the payable line sum matches, else None.

    When the itemized sum already reconciles to a printed total, per-line
    qty × rate deviations are the bill's own structure (per-line discounts,
    taxes) — not extraction errors.
    """
    amounts = [a for a in (printed_totals or {}).values()
               if isinstance(a, (int, float)) and a > 0]
    if not amounts:
        return None
    payable_sum = compute_payable_line_sum(items)
    for anchor in amounts:
        if abs(payable_sum - anchor) <= _completeness_tolerance(anchor):
            return anchor
    return None
