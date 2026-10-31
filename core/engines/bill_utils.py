"""Bill-line helpers: numeric parsing, quantity / rate / amount resolution, dates, consumables, rollups, arithmetic checks."""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
import logging
import re


logger = logging.getLogger(__name__)


# Bill document types used across digitization, master sync, and bill-processing modules.
STANDARD_BILL_DOCUMENT_TYPES: Set[str] = {
    "FINAL_HOSPITAL_BILL",
    "ITEMIZED_FINAL_HOSPITAL_BILL",
    "SUMMARY_FINAL_HOSPITAL_BILL",
    "INTERIM_RUNNING_BILL",
    "MEDICINE_PHARMACY_BILLS",
}


_STANDARD_BILL_DOCUMENT_TYPES_UPPER = {t.upper() for t in STANDARD_BILL_DOCUMENT_TYPES}


def is_bill_document_type(document_type: str) -> bool:
    """True for hospital/pharmacy bills and invoices that require line-item extraction."""
    return document_type.upper().replace(" ", "_") in _STANDARD_BILL_DOCUMENT_TYPES_UPPER


# Main-bill hierarchy (PRD/TL rule): the ITEMIZED bill is the main hospital bill; a
# summary/consolidated bill is the FALLBACK main when no itemized exists ("when the itemized
# bill is missing, fall back to the summary/combined bill"). Lower index = higher priority.
_HOSPITAL_BILL_HIERARCHY: Tuple[str, ...] = (
    "ITEMIZED_FINAL_HOSPITAL_BILL",
    "FINAL_HOSPITAL_BILL",
    "SUMMARY_FINAL_HOSPITAL_BILL",
    "INTERIM_RUNNING_BILL",
)


_HOSPITAL_BILL_SOURCE_LABELS: Dict[str, str] = {
    "ITEMIZED_FINAL_HOSPITAL_BILL": "itemized",
    "FINAL_HOSPITAL_BILL": "itemized",
    "SUMMARY_FINAL_HOSPITAL_BILL": "summary_fallback",
    "INTERIM_RUNNING_BILL": "interim_fallback",
}


def _hospital_bill_rank(document_type: Optional[str]) -> Optional[int]:
    normalized = (document_type or "").upper().replace(" ", "_")
    try:
        return _HOSPITAL_BILL_HIERARCHY.index(normalized)
    except ValueError:
        return None


def resolve_main_hospital_bill(
    items: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Pick the MAIN hospital bill document for a claim.

    Hierarchy: itemized/final > summary (fallback) > interim (fallback). Among documents of
    the same rank, the one with the largest line-item total wins (the fullest bill).

    Returns (main_bill_document_uuid, main_bill_source) where main_bill_source is
    "itemized" | "summary_fallback" | "interim_fallback"; (None, None) when the claim has no
    hospital-bill document (pharmacy-only claims).
    """
    doc_rank: Dict[str, int] = {}
    doc_type: Dict[str, str] = {}
    doc_total: Dict[str, float] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rank = _hospital_bill_rank(item.get("document_type"))
        if rank is None:
            continue
        doc_uuid = str(item.get("document_uuid") or "")
        if not doc_uuid:
            continue
        doc_rank[doc_uuid] = rank
        doc_type[doc_uuid] = (
            str(item.get("document_type") or "").upper().replace(" ", "_")
        )
        raw_amount = item.get("net_amount")
        if raw_amount is None:
            raw_amount = item.get("total_amount")
        try:
            doc_total[doc_uuid] = doc_total.get(
                doc_uuid, 0.0) + float(raw_amount or 0.0)
        except (TypeError, ValueError):
            doc_total.setdefault(doc_uuid, 0.0)

    if not doc_rank:
        return None, None

    main_uuid = min(
        doc_rank,
        key=lambda uuid_: (doc_rank[uuid_], -doc_total.get(uuid_, 0.0)),
    )
    source = _HOSPITAL_BILL_SOURCE_LABELS.get(
        doc_type.get(main_uuid, ""), "itemized")
    return main_uuid, source


_PLACEHOLDER_STRINGS = frozenset({"na", "n/a", "null", "none", "-"})


# Unicode whitespace (NBSP, thin space, etc.) that breaks exact category matching.
_UNICODE_WHITESPACE_RE = re.compile(r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000]+")


def normalize_category_token(value: Any) -> str:
    """
    Strip surrounding and internal unicode whitespace and optional wrapping quotes
    from a billing category token before routing or comparison.
    """
    if value is None:
        return ""
    text = _UNICODE_WHITESPACE_RE.sub(" ", str(value)).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


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


_CLASSIFICATION_RATIONALE_PATTERNS = (
    re.compile(
        r"\bis (a|an) (surgical|medical|lab|pharmacy|room|hospital|diagnostic)\b",
        re.I,
    ),
    re.compile(
        r"\bis (a|an) \w+ (procedure|test|charge|item|service|medicine|drug)\b",
        re.I,
    ),
    re.compile(r"\bbilling type\b", re.I),
    re.compile(r"\bclassif", re.I),
)


def looks_like_classification_rationale(text: Any) -> bool:
    """True when text is a module rationale (e.g. NMP category), not a bill line label."""
    if text is None:
        return False
    stripped = str(text).strip()
    if not stripped:
        return False
    # Flagging blocks are appended after the category one-liner.
    first_line = stripped.split("\n\n", 1)[0].strip()
    lower = first_line.lower()
    if lower.startswith("item '") and "was not included" in lower:
        return True
    if lower.startswith("passed through"):
        return True
    if any(pattern.search(lower) for pattern in _CLASSIFICATION_RATIONALE_PATTERNS):
        return True
    # NMP billing-type one-liners: short declarative sentences without bill identifiers.
    if (
        first_line.endswith(".")
        and len(first_line) <= 150
        and not re.search(r"\d", first_line)
    ):
        if re.search(r"\b(is|are) (a|an|administrative|the)\b", lower):
            return True
        if re.search(
            r"\b(consumable item|pharmaceutical drug|nursing procedure|"
            r"room rent charges|professional fees|administrative services)\b",
            lower,
        ):
            return True
        if re.search(r"\b(item|drug|procedure|service|charges|fees)\.\s*$", lower):
            return True
    return False


def is_usable_bill_item_name(val: Any) -> bool:
    """True when a value is a real bill line label (not NA / category rationale)."""
    if is_placeholder_value(val):
        return False
    return not looks_like_classification_rationale(val)


def coalesce_bill_item_name(item: Dict[str, Any]) -> Optional[str]:
    """Return the best display name for a bill line, or None if only placeholders."""
    if not isinstance(item, dict):
        return None

    name = coalesce_non_placeholder(
        item.get("item_name"),
        item.get("service_name"),
        item.get("description"),
        item.get("name"),
        item.get("printed_label"),
    )
    if name is not None:
        name_str = str(name).strip()
        if is_usable_bill_item_name(name_str):
            return name_str
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


def resolve_bill_line_quantity(item: Dict[str, Any]) -> Optional[float]:
    """Resolve quantity from bill line aliases."""
    raw = coalesce_non_placeholder(item.get("quantity"), item.get("qty"))
    return parse_numeric_bill_value(raw)


def resolve_bill_line_unit_rate(item: Dict[str, Any]) -> Optional[float]:
    """Resolve unit rate from bill line aliases (unit_rate, unit_price, rate)."""
    raw = coalesce_non_placeholder(
        item.get("unit_rate"),
        item.get("unit_price"),
        item.get("rate"),
    )
    return parse_numeric_bill_value(raw)


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


def get_bill_line_mandatory_field_violations(item: Dict[str, Any]) -> List[str]:
    """Return list of missing mandatory field names for one bill line."""
    missing: List[str] = []
    if resolve_bill_line_quantity(item) is None:
        missing.append("quantity")
    if resolve_bill_line_unit_rate(item) is None:
        missing.append("unit_rate")
    return missing


_ISO_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


_DMY_DATE_PREFIX_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})")


def normalize_bill_date_string(raw: Any) -> Optional[str]:
    """
    Normalize a digitized date to ISO YYYY-MM-DD, parsing Indian bills day-first.

    Accepts ISO strings (passed through) and dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy.
    Returns None when the value is missing or unparseable. When day-first parsing
    yields an invalid month (>12) the day/month interpretation is swapped.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    m = _ISO_DATE_PREFIX_RE.match(text)
    if m:
        year, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            # Model emitted YYYY-DD-MM; repair to YYYY-MM-DD.
            a, b = b, a
        if 1 <= a <= 12 and 1 <= b <= 31:
            return f"{year:04d}-{a:02d}-{b:02d}"
        return None
    m = _DMY_DATE_PREFIX_RE.match(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if month > 12 and day <= 12:
            # Value was written month-first; swap.
            day, month = month, day
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


_CATEGORY_ROLLUP_NAME_PATTERNS = (
    r"expected\s+cost\s+of",
    r"other\s+hospital\s+expenses",
    r"professional\s+fees",
    r"medicines?\s*[-–]\s*consumables",
    r"per\s+day\s+room\s+rent",
    r"investigation\s*\+\s*diagnostic",
    r"cost\s+of\s+implants",
)


# Standalone section subtotal labels (not individual charge/tax/discount lines).
_SECTION_SUBTOTAL_NAME_PATTERNS = (
    r"\bsub[- ]?total\b",
    r"\bsection\s+total\b",
    r"\bcategory\s+total\b",
    r"\bdepartment\s+total\b",
    r"\bblock\s+total\b",
    r"\bestimate\s+summary\b",
    r"\bbill\s+summary\b",
    # Package-block rollup (Reliance prints components + "Total Packaged Cost").
    r"^total\s+packaged?\s+cost\b",
)


# Category section names followed by "total" (e.g. "Pharmacy Total", "Room Charges Total").
_SECTION_SUBTOTAL_SUFFIX_PATTERN = re.compile(
    r"^(?:"
    r"room|pharma|pharmacy|medicine|medicines|consumable|consumables|"
    r"lab|laboratory|investigation|diagnostic|radiology|surgery|procedure|"
    r"implant|implants|professional|doctor|nursing|icu|ot|"
    r"medical|equipment|service|services|misc|miscellaneous|hospital"
    r")\b[\w\s/&-]{0,40}\s+total\s*$",
    re.IGNORECASE,
)


# Prefix-form category totals (e.g. "Total for GENERAL SURGERIES",
# "Total of Radiology"). Anchored at the start so duration phrasing inside a
# charge name ("Room Rent - Total for 3 days") never matches.
_SECTION_SUBTOTAL_PREFIX_PATTERN = re.compile(
    r"^total\s+(?:for|of)\s+\S",
    re.IGNORECASE,
)


LINE_KIND_LINE_ITEM = "line_item"


LINE_KIND_SECTION_SUBTOTAL = "section_subtotal"


LINE_KIND_ADJUSTMENT = "adjustment"


# NOTE: singular-only by design. Widening these to plurals ("Discounts") makes
# _build_input_items_map strip the row, which breaks the NME negative-adjustment
# pass-through that depends on matching it (see coverage_post_process.py:153-159).
# Tariff needs plural-aware detection and keeps its own patterns in
# the package-scope rules rather than changing membership here.
_BILL_ADJUSTMENT_NAME_PATTERNS = (
    r"\bconcession\b",
    r"\bdiscount\b",
    r"\bless\s+discount\b",
    r"\badjustment\b",
    r"\bround[- ]?off\b",
    r"\brebate\b",
    r"\bcredit\s+note\b",
    r"\bwrite[- ]?off\b",
    r"\bwaiver\b",
)


# Payment/settlement rows printed on bill footers (receipts, advances, deposits,
# payment-mode lines). These are money-flow records, NOT charges, and must never
# enter the payable line-item set. Kept separate from item-level return/reversal
# lines (negative drug returns etc.), which ARE legitimate charge adjustments and
# must stay so category subtotals reconcile (e.g. pharmacy net = issues - returns).
_PAYMENT_SETTLEMENT_NAME_PATTERNS = (
    r"\bpayable\s+by\s+others?\b",
    r"\bamount\s+(?:to\s+be\s+)?received\b",
    r"\bamount\s+paid\b",
    r"\bpaid\s+by\s+(?:patient|tpa|insurer|others?|company)\b",
    r"\b(?:total\s+)?advance(?:s)?\s*(?:received|paid|payment|collection)?\s*(?:\(rs\.?\))?\s*:?\s*$",
    r"\bcash\s+advance\b",
    r"\badvance\s+receipt\b",
    r"\badvance\s*[-–]?\s*card\b",
    r"\bcard\s+ending\b",
    r"\bpaytm\b",
    r"\bgoogle\s*pay\b",
    r"\bphonepe\b",
    r"\bsecurity\s+deposits?\b",
    r"\b(?:patient|total)\s+receipts?\b",
    r"\bmode\s+of\s+payment\b",
    r"\bcheque\b",
    r"\bpay\s+order\b",
    r"\bdrawn\s+on\b",
    r"\bneft\b",
    r"\brtgs\b",
    r"\bbill\s+settlement\b",
    r"\b(?:patient|encounter|deposit)s?\s+refunds?\b",
    r"\brefund\s+of\b",
    r"\bbill\s+outstanding\b",
)


# Rupee tolerance when comparing printed bill subtotals to summed line items.
SUBTOTAL_COMPARE_TOLERANCE = 1.0


def _rollup_check_texts(item: Dict[str, Any]) -> List[str]:
    """Collect lowercase text fields used for category-rollup heuristics."""
    texts: List[str] = []
    for key in ("item_name", "ai_explanation", "name", "description"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            texts.append(val.strip().lower())
    return texts


def item_looks_like_category_rollup(item: Dict[str, Any]) -> bool:
    """Heuristic: item looks like a section/category rollup, not a single charge line."""
    for text in _rollup_check_texts(item):
        if "category rollup" in text or re.search(r"\brollup\s+for\b", text):
            return True

    name = (item.get("item_name") or item.get("name") or "").strip()
    if not name:
        return False
    # A row carrying its own item/SKU code is a real charge line — printed
    # category rollups never do (verified false positive: Lucknow's
    # "Baccirub HRub 500ml(C.Hexdin+Ethanol)Bot", item code BC1-26146, was
    # quarantined as a subtotal and its Rs 998 vanished from master).
    item_code = str(item.get("item_code") or "").strip()
    if item_code and item_code.upper() not in ("NA", "N/A", "NONE", "-"):
        return False
    name_lower = name.lower()
    # "+" inside parentheses/brackets is a drug composition
    # ("(C.Hexdin+Ethanol)"), not a category union — mask before splitting.
    name_outside_parens = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", name)
    plus_segments = [s.strip()
                     for s in re.split(r"\s*\+\s*", name_outside_parens)
                     if s.strip()]
    if len(plus_segments) >= 2 and len(name) > 35:
        return True
    for pattern in _CATEGORY_ROLLUP_NAME_PATTERNS:
        if re.search(pattern, name_lower):
            if len(plus_segments) >= 2 or len(name) > 45:
                return True
            if "expected cost" in name_lower or "other hospital" in name_lower:
                return True
    return False


def _name_looks_like_tax_or_discount_line(name_lower: str) -> bool:
    """True when the row name indicates an itemized tax/discount line, not a section subtotal."""
    if re.search(
        r"\b(cgst|sgst|igst|gst|vat|tax|discount|rebate|round[- ]?off|concession)\b",
        name_lower,
    ):
        return True
    if re.search(r"\d+\s*%", name_lower):
        return True
    return False


def item_looks_like_payment_settlement_row(item: Dict[str, Any]) -> bool:
    """
    True when a row records a payment/settlement money-flow (receipt, advance,
    deposit, payment-mode line like "Cheque/DD ... Drawn on ..."), not a charge.

    Deliberately does NOT match item-level return/reversal lines (negative drug
    returns), which are legitimate charge adjustments needed for category totals.
    """
    if not isinstance(item, dict):
        return False
    name = coalesce_bill_item_name(item) or ""
    name_lower = name.strip().lower()
    if not name_lower:
        return False
    for pattern in _PAYMENT_SETTLEMENT_NAME_PATTERNS:
        if re.search(pattern, name_lower):
            return True
    return False


# Disposable consumables billed to the patient (gloves, syringes, IV sets,
# dressing material, ...). Name-based, mirroring _PAYMENT_SETTLEMENT_NAME_PATTERNS:
# case-insensitive word-boundary regexes over the coalesced line name.
# Deliberately EXCLUDES drugs/injections ("NaCl Inj"), implants (stents/mesh),
# and procedure SERVICES ("IV Cannulation by Cannulation Team") — the noun
# ("cannula") flags, the verb/service ("cannulation") never does (\b handles it).
_CONSUMABLE_NAME_PATTERNS = (
    # -- PPE & apparel --
    r"\bgloves?\b",
    r"\bmasks?\b",
    r"\bn[- ]?95\b",
    r"\bgowns?\b",
    r"\baprons?\b",
    r"\b(?:surgeon'?s?|surgical|bouffant|head|nurse'?s?|disposable)\s+caps?\b",
    r"\bshoe\s+covers?\b",
    r"\bppe\s+kits?\b",
    # -- injection / infusion hardware --
    r"\bsyringes?\b",
    r"\bneedles?\b",
    r"\bcannulae?s?\b",
    r"\bcatheters?\b",
    r"\bvenflon\b",
    r"\bjelco\b",
    r"\bscalp\s+vein\b",
    r"\b(?:i\.?v\.?|bt|blood\s+(?:transfusion|admin(?:istration)?))\s*sets?\b",
    r"\binfusion\s+sets?\b",
    r"\bextension\s+(?:lines?|sets?|tub(?:e|ing)s?)\b",
    r"\bthree\s*[- ]?\s*ways?\b",
    r"\b3[- ]?ways?\b",
    r"\bstop\s*cocks?\b",
    # "PRESSURE MONIT LINE200CM": abbreviated 'monitoring', size glued onto
    # "line" — hence \w* after monit and no trailing \b after line.
    r"\bpressure\s+monit\w*\s*lines?",
    r"\bluer\b",
    r"\bq[- ]?syte\b",
    # -- tubes & drainage --
    r"\b(?:et|endotracheal)\s+tubes?\b",
    r"\bsuction\s+(?:tubes?|catheters?|sets?)\b",
    r"\bryle'?s?\s+tubes?\b",
    r"\bfoley'?s?\b",
    r"\buro\s*bags?\b",
    r"\burine\s+bags?\b",
    r"\b(?:colostomy|urostomy|drainage)\s+bags?\b",
    # -- dressing & absorbents --
    r"\bgau[sz]e\b",
    r"\bswabs?\b",
    r"\bcotton\b",
    r"\bbandages?\b",
    r"\bdressings?\b",
    r"\bleukomed\b",
    r"\btegaderm\b",
    r"\bleukoplast\b",
    r"\bdynaplast\b",
    r"\b(?:iv|i\.v\.?|transparent|adhesive)\s+films?\b",
    r"\bdrapes?\b",
    r"\bcrepe\b",
    r"\bplasters?\b",
    r"\bmicropore\b",
    r"\bgam[gj]ee\b",
    r"\bk[- ]?bind\b",
    r"\bunderpads?\b",
    r"\bdiapers?\b",
    r"\bwipes?\b",
    r"\b(?:maternity|sanitary)\s+pads?\b",
    # -- antiseptics & skin prep (material use, not drug dose forms) --
    r"\bspirits?\b",
    r"\bsaniti[sz]ers?\b",
    r"\bhand\s*rubs?\b",
    r"\bsterillium\b",
    r"\b(?:betadine|povidone(?:[- ]iodine)?|chlorhexidine|savlon|dettol)\s+(?:sol(?:ution)?|scrub|paint)\b",
    # -- monitoring / diagnostic disposables --
    r"\bthermometers?\b",
    r"\blancets?\b",
    r"\belectrodes?\b",
    r"\becg\s+leads?\b",
    r"\b(?:ultrasound|usg|ecg|sonography|lubric\w+)\s+(?:gel|jelly)\b",
    r"\bk[- ]?y\s+jelly\b",
    # -- OT / ward sundries --
    r"\bkidney\s+trays?\b",
    r"\b(?:trolley|camera|probe|equipment|table|mattress)\s+covers?\b",
    r"\b(?:ot|o\.t\.?)\s+accessor(?:y|ies)\b",
    r"\btourniquets?\b",
    r"\bconsumables?\b",
    r"\bdisposables?\b",
)


# Service/procedure context: the row bills WORK (cannulation, catheterization,
# dressing charges), not material — never a consumable even when a noun matches.
_CONSUMABLE_SERVICE_CONTEXT_PATTERNS = (
    r"\bcannulations?\b",
    r"\bcatheteri[sz]ations?\b",
    r"\bintubations?\b",
    r"\b(?:insertion|application|removal|change)\s+charges?\b",
    r"\bdressing\s+charges?\b",
    r"\bprocedure\s+charges?\b",
)


# Drug dose forms: a pharmacy line ("SodiumChlorid0.9%100ml Inj", prefilled
# syringes of a drug) is a drug, not a consumable, even when a material noun
# appears alongside.
_CONSUMABLE_DRUG_FORM_PATTERNS = (
    r"\binj(?:ection)?s?\.?\b",
    r"\btablets?\b",
    r"\bcapsules?\b",
    r"\bsyrup\b",
    r"\bsuspension\b",
    r"\bointment\b",
    r"\bcream\b",
    r"\bpre[- ]?filled\b",
)


def is_consumable_bill_item(item: Dict[str, Any]) -> bool:
    """
    True when a billed line is a disposable consumable (gloves, syringe, IV
    set, dressing material, ...), by deterministic name patterns.

    Never flags drugs/injections, implants, or services ("IV Cannulation" is a
    service; "IV Cannula" is a consumable). Mirrors
    item_looks_like_payment_settlement_row.
    """
    if not isinstance(item, dict):
        return False
    name = coalesce_bill_item_name(item) or ""
    name_lower = name.strip().lower()
    if not name_lower:
        return False
    for pattern in _CONSUMABLE_SERVICE_CONTEXT_PATTERNS:
        if re.search(pattern, name_lower):
            return False
    for pattern in _CONSUMABLE_DRUG_FORM_PATTERNS:
        if re.search(pattern, name_lower):
            return False
    category = str(
        item.get("item_category")
        or item.get("nmp_item_category")
        or item.get("item_type")
        or ""
    ).strip().lower()
    if category in {"consumable", "consumables"}:
        return True
    for pattern in _CONSUMABLE_NAME_PATTERNS:
        if re.search(pattern, name_lower):
            return True
    return False


def item_looks_like_bill_adjustment(item: Dict[str, Any]) -> bool:
    """
    True when a row is a bill-level discount/concession/adjustment or a
    payment/settlement record, not a payable charge.

    Tax lines (CGST/GST/etc.) are excluded — they receive qty/rate defaults instead.
    """
    if not isinstance(item, dict):
        return False
    if item.get("line_kind") == LINE_KIND_ADJUSTMENT:
        return True

    for field in ("item_type", "item_category", "nmp_item_category"):
        category = str(item.get(field) or "").strip().lower()
        if category in {
            "adjustment",
            "discount",
            "concession",
            "round_off",
            "round-off",
            "rebate",
        }:
            return True

    name = coalesce_bill_item_name(item) or ""
    name_lower = name.strip().lower()
    if not name_lower:
        return False

    if item_looks_like_payment_settlement_row(item):
        return True

    if bill_line_looks_like_tax(item):
        return False

    for pattern in _BILL_ADJUSTMENT_NAME_PATTERNS:
        if re.search(pattern, name_lower):
            return True
    return False


def item_looks_like_section_subtotal(item: Dict[str, Any]) -> bool:
    """
    Heuristic: row is a section/category subtotal (display-only), not an itemized charge.
    Includes category rollups and common printed subtotal labels.
    """
    if item.get("line_kind") == LINE_KIND_SECTION_SUBTOTAL:
        return True
    if item_looks_like_category_rollup(item):
        return True

    name = (item.get("item_name") or item.get("name") or "").strip()
    if not name:
        return False
    name_lower = name.lower()
    if _name_looks_like_tax_or_discount_line(name_lower):
        return False

    for pattern in _SECTION_SUBTOTAL_NAME_PATTERNS:
        if re.search(pattern, name_lower):
            return True

    if _SECTION_SUBTOTAL_SUFFIX_PATTERN.match(name.strip()):
        return True

    if _SECTION_SUBTOTAL_PREFIX_PATTERN.match(name):
        # A row carrying a real item/SKU code is a charge line, never a rollup
        # (same guard as item_looks_like_category_rollup — Lucknow Rs 998 lesson).
        item_code = str(item.get("item_code") or "").strip()
        if not item_code or item_code.upper() in ("NA", "N/A", "NONE", "-"):
            return True

    # Short "Grand Total" / "Net Payable" style rows without itemization cues. Batra prints the
    # footer as "Total Bill Amount" / "Net Bill Amount" (2026-10-15: Kimi copied both as charge
    # lines and the master sum doubled); "Total Amount" / "Net Amount" / "Bill Total" are the same row
    # under other hospitals' labels.
    if re.search(
        r"^(?:grand\s+total|gross\s+(?:amount|total)|net\s+(?:payable|amount)|amount\s+payable|bill\s+amount"
        r"|(?:total|net|gross)\s+bill\s+(?:amount|value|total)|bill\s+total|total\s+amount|(?:table|page|column)?\s*total)\s*$",
        name_lower,
    ):
        return True

    return False


def resolve_printed_grand_total_amount(
    footer_amounts: Dict[str, float],
    *,
    computed: Optional[float] = None,
    tolerance: float = SUBTOTAL_COMPARE_TOLERANCE,
) -> Optional[float]:
    """Printed total that the itemised line items should reconcile against.

    When ``computed`` (the line-item / subtotal sum) is known, prefer the printed footer that
    MATCHES it — so neither a smaller Package/Approved amount (AP-Govt: Total 58,669 vs Package
    33,443) nor a larger gross Sales Total (pharmacy Sales 17,051.97 vs net Grand Total 16,869.64
    after returns) creates a false difference. If none matches (or ``computed`` is unknown), fall
    back to the LARGEST printed figure (the gross the items are expected to add up to).
    """
    values: List[float] = []
    for field_id in ("grand_total", "net_payable", "total_amount"):
        amount = footer_amounts.get(field_id)
        if amount not in (None, "", "NA", "N/A", "na", "n/a"):
            try:
                values.append(float(amount))
            except (ValueError, TypeError):
                continue
    if not values:
        return None
    if computed is not None:
        for value in values:
            if abs(value - float(computed)) <= tolerance:
                return value
    return max(values)


def tag_bill_item_line_kind(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the item with line_kind set for display and partitioning."""
    tagged = dict(item)
    if item_looks_like_bill_adjustment(item):
        tagged["line_kind"] = LINE_KIND_ADJUSTMENT
    elif item_looks_like_section_subtotal(item):
        tagged["line_kind"] = LINE_KIND_SECTION_SUBTOTAL
    else:
        tagged.setdefault("line_kind", LINE_KIND_LINE_ITEM)
    return tagged


def partition_bill_items(
    bill_items: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Split bill rows into itemized line items vs section subtotals.

    Section subtotals are tagged with line_kind=section_subtotal for separate UI display
    and must be excluded from line-item total sums.
    """
    if not bill_items:
        return [], []

    line_items: List[Dict[str, Any]] = []
    section_subtotals: List[Dict[str, Any]] = []
    for item in bill_items:
        if not isinstance(item, dict):
            continue
        tagged = tag_bill_item_line_kind(item)
        if tagged.get("line_kind") == LINE_KIND_SECTION_SUBTOTAL:
            section_subtotals.append(tagged)
        else:
            line_items.append(tagged)
    return line_items, section_subtotals


# Rupee tolerance when comparing quantity × unit_rate to line total.
BILL_LINE_ARITHMETIC_TOLERANCE = 1.0


def bill_line_has_arithmetic_mismatch(
    item: Dict[str, Any],
    *,
    tolerance: float = BILL_LINE_ARITHMETIC_TOLERANCE,
) -> bool:
    """
    True when qty, unit rate, and total are all present but qty × rate ≠ total.

    Skips section subtotals and category rollups. Rows with missing qty or rate
    (filled by apply_bill_line_mandatory_defaults) are not flagged.
    """
    if not isinstance(item, dict):
        return False
    if item.get("line_kind") == LINE_KIND_SECTION_SUBTOTAL:
        return False
    if item_looks_like_section_subtotal(item):
        return False

    qty = resolve_bill_line_quantity(item)
    rate = resolve_bill_line_unit_rate(item)
    total = resolve_bill_line_total_amount(item)
    if qty is None or rate is None or total is None:
        return False

    product = round(qty * rate, 2)
    line_total = round(total, 2)
    return abs(product - line_total) > tolerance


def find_bill_lines_with_arithmetic_mismatches(
    items: List[Dict[str, Any]],
    *,
    tolerance: float = BILL_LINE_ARITHMETIC_TOLERANCE,
) -> List[int]:
    """Return indices of bill lines with qty × unit_rate ≠ total_amount."""
    mismatches: List[int] = []
    for idx, item in enumerate(items):
        if bill_line_has_arithmetic_mismatch(item, tolerance=tolerance):
            mismatches.append(idx)
    return mismatches


def exclude_category_rollup_bill_items(
    bill_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Drop section subtotals, category rollups, and discount/concession adjustment rows."""
    if not bill_items:
        return []
    line_items, section_subtotals = partition_bill_items(bill_items)
    payable_items = [
        item for item in line_items
        # Reconciled bill-level adjustments (anchor-guarded at extract) carry
        # the printed discount/round-off into master so sum(master) = NET.
        if item.get("is_reconciled_bill_adjustment")
        or not item_looks_like_bill_adjustment(item)
    ]
    adjustment_excluded = len(line_items) - len(payable_items)
    excluded = len(section_subtotals) + adjustment_excluded
    if excluded:
        logger.info(
            "Excluded non-payable bill items from processing",
            extra={
                "section_subtotal_count": len(section_subtotals),
                "adjustment_count": adjustment_excluded,
                "excluded_count": excluded,
                "remaining_count": len(payable_items),
            },
        )
    return payable_items
