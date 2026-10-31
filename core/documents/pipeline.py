"""The document path: pages → page classification (reviewed by a human) → digitisation of the bill and the other
documents → invoice lines and header facts for the master record, reconciled against the printed total.

    pages = load_claim_pages(folder)                      # or load_file_pages(path) per upload
    predicted = classify_pages(pages, ask)                # one document type per page; a human confirms
    result = digitise_documents(pages, confirmed_types, ask, claim_id=...)
    result.lines, result.document_facts, result.printed_total, result.reconciled
"""
from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.engines.bill_totals import bill_line_looks_like_discount, merge_bill_document_data_from_batches
from core.llm.client import CostMeter, ModelResult, call_model
from core.media.pages import PageImage, batches, encode_for_request
from core.schemas.classification import BILL_TYPES, DOCUMENT_TYPES, PageClassificationBatch
from core.schemas.digitisation import FileDigitizationResponse
from core.schemas.master import InvoiceLine, LineCategory

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_DEFAULTS: Dict[str, Dict[str, Any]] = json.loads(
    (ROOT / "core" / "prompts" / "digitise_payload_defaults.json").read_text(encoding="utf-8"))
STAGE = "claim-settlement-v1"
CLASSIFY_PAGES_PER_REQUEST = 3
BILL_PAGES_PER_REQUEST = 1
DOC_PAGES_PER_REQUEST = 4
# Rows a bill prints to summarise its items (section subtotals, gross / grand total, net payable): kept for the
# reconciliation, never treated as charges.
SUMMARY_ROW = re.compile(r"\b(sub[\s-]?total|gross total|grand total|net payable|net amount|amount payable|total payable|"
                         r"bill total|balance due|amount due)\b|\btotal\s*$", re.I)
ITEM_TYPE_TO_CATEGORY = {"lab": LineCategory.LAB, "room": LineCategory.ROOM, "medical": LineCategory.MEDICAL,
                         "pharma": LineCategory.PHARMA, "surgery": LineCategory.SURGERY, "taxes": LineCategory.TAXES,
                         "professional fees": LineCategory.PROFESSIONAL_FEES, "services": LineCategory.SERVICES,
                         "radiology": LineCategory.RADIOLOGY, "icu": LineCategory.ICU}
Ask = Callable[..., ModelResult]


def make_ask(cache_dir: Optional[Path], meter: Optional[CostMeter] = None, offline: bool = False) -> Ask:
    """A call_model bound to one claim's cache and cost meter."""
    def ask(prompt: str, payload, images, schema, **kw) -> ModelResult:
        return call_model(prompt, payload, images, schema, cache_dir=cache_dir, meter=meter, offline=offline, **kw)
    return ask


@dataclass
class PagePrediction:
    source_file: str
    page_in_file: int
    page_index: int
    document_type: str
    confidence: float


def classify_pages(pages: List[PageImage], ask: Ask, bundle_name: str = "claim.pdf") -> List[PagePrediction]:
    """One document type per page; pages go to the model in small batches with their global index."""
    def run(batch):
        start, chunk = batch
        first, last = start, start + len(chunk) - 1
        intro = (f"Merged PDF filename: {bundle_name}\nFull document page count: {len(pages)} (global 0-based indices 0 .. "
                 f"{len(pages) - 1}).\nTHIS REQUEST covers ONLY global page indices {first} .. {last} ({len(chunk)} page "
                 "image(s) in this batch).\nBATCHED MODE — required pages[] output:\n- One pages[] object per page image "
                 "in this batch (no skipped indices).\n- Each object MUST include page_index (GLOBAL, from the image label) "
                 "AND document_type for that page only.\n- Read the top-of-page header/letterhead before document_type; "
                 "pharmacy/chemist headers → medicine_pharmacy_bills, not hospital bill types.\n- other_documents is ALWAYS "
                 f"valid — use it when unsure.\n- Allowed document_type values: {', '.join(DOCUMENT_TYPES)}")
        labels = [f"--- Page index {start + i} (0-based GLOBAL index) ---" for i in range(len(chunk))]
        return ask("classify_pages", intro, encode_for_request([p.image for p in chunk]), PageClassificationBatch,
                   tag=f"classify_p{first}-{last}", labels=labels, max_tokens=32768)

    predictions = [PagePrediction(p.source_file, p.page_in_file, i, "other_documents", 0.0) for i, p in enumerate(pages)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(run, batches(pages, CLASSIFY_PAGES_PER_REQUEST)):
            for page in result.parsed.pages:
                if 0 <= page.page_index < len(pages):
                    predictions[page.page_index].document_type = page.document_type.value
                    predictions[page.page_index].confidence = page.confidence
    return predictions


def file_types(predictions: List[PagePrediction]) -> Dict[str, str]:
    """Each file's type = the most common type among its pages."""
    by_file: Dict[str, Counter] = {}
    for p in predictions:
        by_file.setdefault(p.source_file, Counter())[p.document_type] += 1
    return {name: counts.most_common(1)[0][0] for name, counts in by_file.items()}


@dataclass
class DigitisedClaim:
    lines: List[InvoiceLine] = field(default_factory=list)
    discount_rows: List[Dict[str, Any]] = field(default_factory=list)
    summary_rows: List[Dict[str, Any]] = field(default_factory=list)
    document_facts: Dict[str, str] = field(default_factory=dict)
    printed_total: Optional[float] = None
    reconciled: Optional[bool] = None
    raw: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)   # file -> digitisation responses
    calls: List[ModelResult] = field(default_factory=list)


def _amount(text: Any) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(text or ""))
    return float(m.group(0).replace(",", "")) if m else None


def _date(text: Any) -> Optional[date]:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(text or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def digitise_file(name: str, doc_type: str, file_pages: List[PageImage], ask: Ask, claim_id: str) -> List[ModelResult]:
    """Bills one page per request, other documents up to four, with the default extraction configuration."""
    is_bill = doc_type in BILL_TYPES
    defaults = PAYLOAD_DEFAULTS.get(doc_type.upper()) or PAYLOAD_DEFAULTS["OTHER_DOCUMENTS"]

    def run(batch):
        start, chunk = batch
        numbers = [p.page_in_file for p in chunk]
        payload = {"claim_id": claim_id, "stage": STAGE, "document_type": doc_type, "document_uuid": name, **defaults,
                   "page_numbers": numbers, "total_pages": len(file_pages), "pages_per_request": len(chunk)}
        return ask("digitise_bill" if is_bill else "digitise_doc", payload, encode_for_request([p.image for p in chunk]),
                   FileDigitizationResponse, tag=f"digitise_{Path(name).stem}_p{numbers[0]}-{numbers[-1]}", max_tokens=32768)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(run, batches(file_pages, BILL_PAGES_PER_REQUEST if is_bill else DOC_PAGES_PER_REQUEST)))


def _facts_from_fields(fields: List[Dict[str, Any]], facts: Dict[str, str]) -> None:
    wanted = {"patient name": "claimant_name", "policy number": "policy_number", "policy no": "policy_number",
              "hospital name": "provider_name", "admission date": "admission_date", "discharge date": "discharge_date",
              "bill number": "invoice_no", "invoice number": "invoice_no", "net payable": "net_payable", "grand total": "grand_total"}
    for f in fields:
        label = f"{f.get('field_id', '')} {f.get('field_alias', '')}".lower().replace("_", " ")
        value = str(f.get("value") or "").strip()
        if not value:
            continue
        for key, out in wanted.items():
            if key in label and out not in facts:
                facts[out] = value


def digitise_documents(pages: List[PageImage], confirmed: Dict[str, str], ask: Ask, *, claim_id: str,
                       provider_id: Optional[str] = None) -> DigitisedClaim:
    """confirmed: file name -> document type (after the human review). Returns master-ready lines and facts."""
    out = DigitisedClaim()
    by_file: Dict[str, List[PageImage]] = {}
    for p in pages:
        by_file.setdefault(p.source_file, []).append(p)
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {name: pool.submit(digitise_file, name, confirmed.get(name, "other_documents"), fp, ask, claim_id)
                for name, fp in by_file.items()}
        results = {name: job.result() for name, job in jobs.items()}
    serial = 0
    for name, file_results in results.items():
        out.calls.extend(file_results)
        dumps = [r.parsed.model_dump() for r in file_results]
        out.raw[name] = dumps
        footer = merge_bill_document_data_from_batches(dumps)
        _facts_from_fields(footer["fields"], out.document_facts)
        if confirmed.get(name) not in BILL_TYPES:
            continue
        invoice_no = out.document_facts.get("invoice_no") or Path(name).stem
        for result in file_results:
            data = result.parsed.bill_data
            for item in (data.bill_items if data else []):
                row = item.model_dump()
                if SUMMARY_ROW.search(item.item_name or ""):
                    out.summary_rows.append(row)
                    continue
                if bill_line_looks_like_discount(row):
                    out.discount_rows.append(row)
                    continue
                serial += 1
                category = ITEM_TYPE_TO_CATEGORY.get((item.item_type or "").strip().lower())
                out.lines.append(InvoiceLine(
                    line_id=f"{claim_id}:{invoice_no}:{serial}", claim_id=claim_id, invoice_no=invoice_no, serial_no=serial,
                    service_date=_date(item.item_date), code=item.item_code, description=item.item_name, category=category,
                    quantity=item.quantity or 1.0, unit_price=item.unit_price, amount=float(item.total_amount),
                    provider_id=provider_id, document_id=name, page=item.page_number))
    printed = _amount(out.document_facts.get("net_payable")) or _amount(out.document_facts.get("grand_total"))
    out.printed_total = printed
    if printed is not None and out.lines:
        total = round(sum(l.amount for l in out.lines) + sum(float(r.get("total_amount") or 0) for r in out.discount_rows), 2)
        out.reconciled = abs(total - printed) <= 1.0
    return out
