"""Bill-line helpers: numeric parsing, line amount resolution, tax-row detection."""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Optional
import re


_PLACEHOLDER_STRINGS = frozenset({"na", "n/a", "null", "none", "-"})


def is_placeholder_value(val: Any) -> bool:
    """True if value should be treated as missing (NA, blank, null)."""
    if val is None:
        return True
    if isinstance(val, str):
        normalized = val.strip().lower()
        return not normalized or normalized in _PLACEHOLDER_STRINGS
    return False


def coalesce_non_placeholder(*values: Any) -> Any:
    """Return the first value that is not a placeholder; else None."""
    for value in values:
        if not is_placeholder_value(value):
            return value
    return None


def parse_numeric_bill_value(val: Any) -> Optional[float]:
    """Parse a bill numeric field; return None if missing, placeholder, or non-numeric."""
    if is_placeholder_value(val):
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    if isinstance(val, str):
        cleaned = val.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def resolve_bill_line_total_amount(item: Dict[str, Any]) -> Optional[float]:
    """Resolve line total from common amount field aliases."""
    raw = coalesce_non_placeholder(
        item.get("total_amount"),
        item.get("total"),
        item.get("amount"),
        item.get("net_amount"),
        item.get("billed_amount"),
        item.get("original_amount"),
        item.get("approved_amount"),
    )
    return parse_numeric_bill_value(raw)


def bill_line_looks_like_tax(item: Dict[str, Any]) -> bool:
    """
    Heuristic: GST/VAT/surcharge lines that often have amount only (no qty × rate).

    Digitization frequently omits quantity and unit_rate on tax rows; defaults are applied
    before mandatory-field validation (qty=1, unit_rate=line total).
    """
    for field in ("item_type", "item_category", "nmp_item_category"):
        category = str(item.get(field) or "").strip().lower()
        if category in {"taxes", "tax"}:
            return True

    name = (
        item.get("item_name")
        or item.get("service_name")
        or item.get("description")
        or ""
    )
    name_lower = str(name).strip().lower()
    if not name_lower:
        return False

    if re.search(r"\b(cgst|sgst|igst|gst|vat|cess)\b", name_lower):
        return True
    if re.search(r"\b(cgst|sgst|igst|gst)\s*@\s*[\d.]+\s*%?", name_lower):
        return True
    if re.search(r"\b(sales\s+)?tax(es)?\b", name_lower):
        return True
    return False
