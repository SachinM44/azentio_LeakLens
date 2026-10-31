"""Repair of extracted bill rows against the section subtotals printed on the bill."""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import logging
import re


logger = logging.getLogger(__name__)


_MONEY_TOLERANCE = 0.01


_LEADING_TOTAL_RE = re.compile(r"^\s*total\s+(?:for|of)\s+", re.IGNORECASE)


_TRAILING_SUBTOTAL_RE = re.compile(
    r"\s*\(?\s*sub\s*-?\s*total\s*\)?\s*$", re.IGNORECASE
)


_TRAILING_TOTAL_RE = re.compile(r"\s+total\s*$", re.IGNORECASE)


def _normalize_section_text(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _strip_subtotal_decoration(label: str) -> str:
    stripped = _LEADING_TOTAL_RE.sub("", str(label or ""))
    stripped = _TRAILING_SUBTOTAL_RE.sub("", stripped)
    stripped = _TRAILING_TOTAL_RE.sub("", stripped)
    return stripped


def match_section_subtotal_label(subtotal_label: str, section_name: str) -> bool:
    """True when a printed subtotal row belongs to the named section."""
    label_core = _normalize_section_text(_strip_subtotal_decoration(subtotal_label))
    section_core = _normalize_section_text(section_name)
    if not label_core or not section_core:
        return False
    return (
        label_core == section_core
        or label_core.startswith(section_core)
        or section_core.startswith(label_core)
    )


def _row_amount(row: Dict[str, Any]) -> Optional[float]:
    try:
        return round(float(row.get("total_amount")), 2)
    except (TypeError, ValueError):
        return None


def _row_qty_rate(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    try:
        qty = float(row.get("quantity")) if row.get("quantity") is not None else None
    except (TypeError, ValueError):
        qty = None
    try:
        rate = (
            float(row.get("unit_price")) if row.get("unit_price") is not None else None
        )
    except (TypeError, ValueError):
        rate = None
    return qty, rate


def _is_single_digit_substitution(original: float, corrected: float) -> bool:
    """True when the two money values differ in exactly one digit position."""
    a = f"{original:.2f}"
    b = f"{corrected:.2f}"
    if len(a) != len(b):
        return False
    diffs = [
        (ca, cb)
        for ca, cb in zip(a, b)
        if ca != cb
    ]
    return len(diffs) == 1 and diffs[0][0].isdigit() and diffs[0][1].isdigit()


def repair_rows_against_section_subtotals(
    line_items: List[Dict[str, Any]],
    section_subtotals: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (repaired copy of line_items, human-readable repair notes).

    A repair fires only when a section's children disagree with its printed
    subtotal AND exactly one child admits a correction of exactly that delta,
    established either by the row's own qty x rate identity or by a unique
    single-digit substitution. Everything else is left untouched.
    """
    repaired = [dict(row) for row in line_items]
    notes: List[str] = []
    if not repaired or not section_subtotals:
        return repaired, notes

    sections: Dict[str, List[int]] = {}
    section_display: Dict[str, str] = {}
    for idx, row in enumerate(repaired):
        section_name = row.get("section_name")
        key = _normalize_section_text(section_name)
        if not key:
            continue
        sections.setdefault(key, []).append(idx)
        section_display.setdefault(key, str(section_name))

    if not sections:
        return repaired, notes

    for subtotal in section_subtotals:
        if not isinstance(subtotal, dict):
            continue
        label = str(subtotal.get("item_name") or "")
        printed = _row_amount(subtotal)
        if printed is None:
            continue
        matched_key = next(
            (
                key
                for key in sections
                if match_section_subtotal_label(label, section_display[key])
            ),
            None,
        )
        if matched_key is None:
            continue

        indices = sections[matched_key]
        amounts = [_row_amount(repaired[i]) for i in indices]
        if any(a is None for a in amounts):
            continue
        children_sum = round(sum(amounts), 2)
        delta = round(children_sum - printed, 2)
        if abs(delta) <= _MONEY_TOLERANCE:
            continue

        identity_candidates: List[Tuple[int, float]] = []
        digit_candidates: List[Tuple[int, float]] = []
        for i in indices:
            row = repaired[i]
            amount = _row_amount(row)
            corrected = round(amount - delta, 2)
            if corrected <= 0:
                continue
            qty, rate = _row_qty_rate(row)
            if qty is not None and rate is not None and qty > 0 and rate > 0:
                expected = round(qty * rate, 2)
                identity_holds_now = abs(expected - amount) <= _MONEY_TOLERANCE
                identity_holds_after = abs(expected - corrected) <= _MONEY_TOLERANCE
                if not identity_holds_now and identity_holds_after:
                    identity_candidates.append((i, corrected))
                    continue
                if identity_holds_now and not identity_holds_after:
                    # Correcting the amount would break a currently-consistent
                    # row unless qty==1 and the rate (== amount) moves with it.
                    if not (
                        abs(qty - 1.0) <= 1e-9
                        and abs(rate - amount) <= _MONEY_TOLERANCE
                    ):
                        continue
            if _is_single_digit_substitution(amount, corrected):
                digit_candidates.append((i, corrected))

        chosen: Optional[Tuple[int, float]] = None
        if len(identity_candidates) == 1:
            chosen = identity_candidates[0]
        elif not identity_candidates and len(digit_candidates) == 1:
            chosen = digit_candidates[0]
        if chosen is None:
            continue

        idx, corrected = chosen
        row = repaired[idx]
        old_amount = _row_amount(row)
        qty, rate = _row_qty_rate(row)
        row["total_amount"] = corrected
        if (
            qty is not None
            and rate is not None
            and abs(qty - 1.0) <= 1e-9
            and abs(rate - old_amount) <= _MONEY_TOLERANCE
        ):
            row["unit_price"] = corrected
        row["checksum_repaired"] = True
        note = (
            f'section "{label}": row "{row.get("item_name")}" amount '
            f"{old_amount:.2f} -> {corrected:.2f} snapped to printed subtotal "
            f"{printed:.2f}"
        )
        notes.append(note)
        logger.info(
            "bill_section_checksum_repaired",
            extra={
                "section_label": label,
                "row_name": str(row.get("item_name"))[:80],
                "old_amount": old_amount,
                "corrected_amount": corrected,
                "printed_subtotal": printed,
            },
        )

    return repaired, notes
