"""Strict duplicate-line detection on a bill: same item, same amount, same usage date."""
from __future__ import annotations

import os
from enum import Enum

# Amount tolerance and reason codes.
AMOUNT_EPSILON_RATIO = float(os.environ.get("INVOICE_FLAG_AMOUNT_EPSILON_RATIO", "0.005"))


class InvoiceFlagReasonCode(str, Enum):
    """Stable reason codes for claim and line-level flags."""

    EXACT_DUPLICATE_AMOUNT = "exact_duplicate_amount"
    NEAR_DUPLICATE_SUBMISSION = "near_duplicate_submission"
    CROSS_INVOICE_DUPLICATE = "cross_invoice_duplicate"
    OUTLIER_REQUESTED_ITEM = "outlier_requested_item"
    TEMPORAL_MISMATCH = "temporal_mismatch"


from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
import re


def _norm_name(name: str) -> str:
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _amount_close(a: float, b: float) -> bool:
    if a == b:
        return True
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base <= AMOUNT_EPSILON_RATIO


def _item_code(item: Dict[str, Any]) -> str:
    return str(item.get("item_code") or "").strip()


def _line_amount(item: Dict[str, Any]) -> float:
    """Bill line amount for duplicate detection (master rows may use net_amount)."""
    raw = item.get("total_amount")
    if raw is None:
        raw = item.get("net_amount")
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def strict_duplicate_identity_match(
    item_a: Dict[str, Any], item_b: Dict[str, Any]
) -> bool:
    """
    Return True when two lines represent the same billed item by strict identity.

    Requires exact normalized item_name match OR exact non-empty item_code match.
    Fuzzy / partial name similarity is intentionally excluded.
    """
    ni = _norm_name(str(item_a.get("item_name") or ""))
    nj = _norm_name(str(item_b.get("item_name") or ""))
    if ni and ni == nj:
        return True
    code_i = _item_code(item_a)
    code_j = _item_code(item_b)
    return bool(code_i and code_i == code_j)


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
)


def _norm_date_str(raw: str) -> Optional[str]:
    """Normalize a bill line date to YYYY-MM-DD when parseable."""
    s = (raw or "").strip()
    if not s:
        return None
    iso_prefix = re.match(r"^(20\d{2}-\d{2}-\d{2})", s)
    if iso_prefix:
        return iso_prefix.group(1)
    candidate = s[:10] if len(s) > 10 else s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def item_date_key(item: Dict[str, Any]) -> Optional[str]:
    """Return normalized item_date for duplicate grouping, or None if unknown."""
    for key in ("item_date", "date_of_usage", "date"):
        val = item.get(key)
        if val is None:
            continue
        normalized = _norm_date_str(str(val))
        if normalized:
            return normalized
    return None


def dates_allow_duplicate_comparison(
    item_a: Dict[str, Any], item_b: Dict[str, Any]
) -> bool:
    """
    Return False when both lines have known usage dates on different days.

    Same procedure/charge on different dates is legitimate repeat billing, not a duplicate.
    """
    date_a = item_date_key(item_a)
    date_b = item_date_key(item_b)
    if date_a and date_b and date_a != date_b:
        return False
    return True


_DEPENDENT_CHARGE_QUALIFIERS = {
    "additional",
    "addl",
    "aditional",
    "addtional",
    "additioanl",
    "extra",
}


_DEPENDENT_CHARGE_WORDS = {"charge", "charges", "surcharge", "surcharges"}


_DEPENDENT_CHARGE_STOPWORDS = {
    "additional",
    "addl",
    "aditional",
    "addtional",
    "additioanl",
    "extra",
    "charge",
    "charges",
    "surcharge",
    "surcharges",
    "for",
    "of",
    "on",
    "to",
    "towards",
    "the",
    "and",
    "fee",
    "fees",
}


def _tokenize_normalized_name(name: str) -> Set[str]:
    tokens = {token for token in _norm_name(name).split() if token}
    if "xray" in tokens:
        tokens.update({"x", "ray"})
    if {"x", "ray"}.issubset(tokens):
        tokens.add("xray")
    return tokens


def _is_dependent_charge_name(name: str) -> bool:
    tokens = _tokenize_normalized_name(name)
    return bool(
        tokens & _DEPENDENT_CHARGE_QUALIFIERS
        and tokens & _DEPENDENT_CHARGE_WORDS
    )


def _dependent_charge_anchor_tokens(name: str) -> Set[str]:
    return _tokenize_normalized_name(name) - _DEPENDENT_CHARGE_STOPWORDS


def dependent_charge_parent_index(
    bill_items: List[Dict[str, Any]], line_index: int
) -> Optional[int]:
    """
    Link contextual charge rows, such as "additional charges for x ray", to a nearby
    parent service line on the same date.

    If two otherwise identical dependent charges point to different parent service
    rows, they represent separate billable events rather than duplicate submissions.
    """
    if line_index < 0 or line_index >= len(bill_items):
        return None

    item = bill_items[line_index]
    name = str(item.get("item_name") or "")
    if not _is_dependent_charge_name(name):
        return None

    anchor_tokens = _dependent_charge_anchor_tokens(name)
    if not anchor_tokens:
        return None

    candidates: List[Tuple[int, int, int]] = []
    for candidate_idx, candidate in enumerate(bill_items):
        if candidate_idx == line_index:
            continue
        candidate_name = str(candidate.get("item_name") or "")
        if _is_dependent_charge_name(candidate_name):
            continue
        if not dates_allow_duplicate_comparison(item, candidate):
            continue

        candidate_tokens = _tokenize_normalized_name(candidate_name)
        if not candidate_tokens:
            continue
        overlap = anchor_tokens & candidate_tokens
        if not overlap:
            continue
        if not anchor_tokens.issubset(candidate_tokens) and (
            len(overlap) / max(len(anchor_tokens), 1)
        ) < 0.6:
            continue

        # Prefer the nearest prior service row, which matches how invoice add-on
        # charges are usually listed. Fall back to nearest following row.
        direction_rank = 0 if candidate_idx < line_index else 1
        candidates.append((direction_rank, abs(candidate_idx - line_index), candidate_idx))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][2]


def contextual_items_allow_duplicate_comparison(
    bill_items: List[Dict[str, Any]],
    line_index_a: int,
    line_index_b: int,
) -> bool:
    """Return False when repeated dependent charges attach to different parents."""
    if not dates_allow_duplicate_comparison(
        bill_items[line_index_a], bill_items[line_index_b]
    ):
        return False

    parent_a = dependent_charge_parent_index(bill_items, line_index_a)
    parent_b = dependent_charge_parent_index(bill_items, line_index_b)
    if parent_a is not None and parent_b is not None and parent_a != parent_b:
        return False
    return True


@dataclass
class DeterministicSignals:
    """Per-line indices and claim-level duplicate pairings."""

    exact_dup_groups: List[List[int]] = field(default_factory=list)
    near_dup_pairs: List[Tuple[int, int]] = field(default_factory=list)
    cross_invoice_dup_pairs: List[Tuple[int, int]] = field(
        default_factory=list
    )  # (local_idx, peer_idx) peer_idx negative or use offset — we'll use (line, peer_line) with peer as global negative index: simpler store as tuple (i, j, "cross") with j being index in flattened peer list

    line_to_reasons: Dict[int, Set[str]] = field(default_factory=lambda: defaultdict(set))
    line_dup_neighbors: Dict[int, Set[int]] = field(default_factory=lambda: defaultdict(set))


def collect_strict_duplicate_candidate_pairs(
    bill_items: List[Dict[str, Any]],
    existing_pairs: Optional[List[Tuple[int, int]]] = None,
    max_pairs: int = 120,
) -> List[Tuple[int, int]]:
    """
    Build Gemini candidate pairs: strict identity (exact name or exact code),
    close amount, and allowed date/parent context only.
    """
    seen: Set[Tuple[int, int]] = set(existing_pairs or [])
    out: List[Tuple[int, int]] = list(existing_pairs or [])[:max_pairs]
    if len(out) >= max_pairs:
        return out[:max_pairs]

    n = len(bill_items)
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in seen or (j, i) in seen:
                continue
            if not contextual_items_allow_duplicate_comparison(bill_items, i, j):
                continue
            ai = bill_items[i]
            aj = bill_items[j]
            amt_i = _line_amount(ai)
            amt_j = _line_amount(aj)
            if not _amount_close(amt_i, amt_j):
                continue
            if not strict_duplicate_identity_match(ai, aj):
                continue
            seen.add((i, j))
            out.append((i, j))
            if len(out) >= max_pairs:
                return out
    return out


def _flatten_peer_lines(peer_bills: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not peer_bills:
        return out
    for pb in peer_bills:
        items = pb.get("bill_items") or []
        for it in items:
            out.append(dict(it))
    return out


def run_deterministic(
    bill_items: List[Dict[str, Any]],
    peer_bills: Optional[List[Dict[str, Any]]] = None,
) -> DeterministicSignals:
    sig = DeterministicSignals()
    n = len(bill_items)
    if n == 0:
        return sig

    # Index by normalized name + amount + usage date (same name/amount on different days is valid).
    # Contextual dependent charges also include their parent line, so one add-on per repeated
    # parent service is not treated as an exact duplicate.
    by_key: Dict[Tuple[str, str, str, str], List[int]] = defaultdict(list)
    for i, item in enumerate(bill_items):
        nm = _norm_name(str(item.get("item_name") or ""))
        amt = _line_amount(item)
        date_part = item_date_key(item) or ""
        parent_idx = dependent_charge_parent_index(bill_items, i)
        parent_part = f"parent:{parent_idx}" if parent_idx is not None else ""
        key = (nm, f"{amt:.2f}", date_part, parent_part)
        by_key[key].append(i)

    for _key, indices in by_key.items():
        if len(indices) > 1:
            sig.exact_dup_groups.append(sorted(indices))
            for a in indices:
                for b in indices:
                    if a != b:
                        sig.line_dup_neighbors[a].add(b)
                        sig.line_to_reasons[a].add(InvoiceFlagReasonCode.EXACT_DUPLICATE_AMOUNT.value)

    # Code-based duplicate: same exact item_code, close amount, same date/context;
    # different display names only (exact name matches are handled by exact_dup_groups).
    for i in range(n):
        for j in range(i + 1, n):
            ai = bill_items[i]
            aj = bill_items[j]
            if not contextual_items_allow_duplicate_comparison(bill_items, i, j):
                continue
            amt_i = _line_amount(ai)
            amt_j = _line_amount(aj)
            if not _amount_close(amt_i, amt_j):
                continue
            ni = _norm_name(str(ai.get("item_name") or ""))
            nj = _norm_name(str(aj.get("item_name") or ""))
            if ni == nj:
                continue  # already covered by exact key groups
            code_i = _item_code(ai)
            code_j = _item_code(aj)
            if code_i and code_i == code_j:
                sig.near_dup_pairs.append((i, j))
                sig.line_dup_neighbors[i].add(j)
                sig.line_dup_neighbors[j].add(i)
                sig.line_to_reasons[i].add(InvoiceFlagReasonCode.NEAR_DUPLICATE_SUBMISSION.value)
                sig.line_to_reasons[j].add(InvoiceFlagReasonCode.NEAR_DUPLICATE_SUBMISSION.value)

    # Cross-invoice: match against peer bill lines (by name+amount or code+amount)
    peers = _flatten_peer_lines(peer_bills)
    for i, item in enumerate(bill_items):
        ni = _norm_name(str(item.get("item_name") or ""))
        amt_i = _line_amount(item)
        code_i = (item.get("item_code") or "").strip()
        for pj, peer in enumerate(peers):
            if not dates_allow_duplicate_comparison(item, peer):
                continue
            amt_p = _line_amount(peer)
            if not _amount_close(amt_i, amt_p):
                continue
            np_ = _norm_name(str(peer.get("item_name") or ""))
            code_p = (peer.get("item_code") or "").strip()
            if ni and ni == np_:
                sig.cross_invoice_dup_pairs.append((i, pj))
                sig.line_to_reasons[i].add(InvoiceFlagReasonCode.CROSS_INVOICE_DUPLICATE.value)
            elif code_i and code_i == code_p:
                sig.cross_invoice_dup_pairs.append((i, pj))
                sig.line_to_reasons[i].add(InvoiceFlagReasonCode.CROSS_INVOICE_DUPLICATE.value)

    return sig
