"""The document path: pages → page classification (reviewed by a human) → digitisation of the bill and the other
documents → invoice lines and header facts for the master record, reconciled against the printed total.

    pages = load_claim_pages(folder)                      # or load_file_pages(path) per upload
    predicted = classify_pages(pages, ask)                # one document type per page; a human confirms
    result = digitise_documents(pages, confirmed_types, ask, claim_id=...)
    result.lines, result.document_facts, result.printed_total, result.reconciled
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.engines.bill_totals import bill_line_looks_like_discount, merge_bill_document_data_from_batches
from core.llm.client import PRIMARY_MODEL, CostMeter, ModelResult, call_model
from core.media.pages import PageImage, batches, encode_for_request
from core.schemas.classification import BILL_TYPES, DOCUMENT_TYPES, PageClassificationBatch
from core.schemas.digitisation import FileDigitizationResponse
from core.schemas.master import InvoiceLine, LineCategory

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_DEFAULTS: Dict[str, Dict[str, Any]] = json.loads(
    (ROOT / "core" / "prompts" / "digitise_payload_defaults.json").read_text(encoding="utf-8"))
STAGE = "claim-review"
# One page per request everywhere, all pages of all files at once: the wall time is the slowest page, not the sum.
CLASSIFY_PAGES_PER_REQUEST = 1
BILL_PAGES_PER_REQUEST = 1
DOC_PAGES_PER_REQUEST = 1
MAX_PARALLEL_CALLS = 16
KIMI_MODEL = "bedrock/moonshotai.kimi-k2.5"
DEFAULT_DOC_MODEL = "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"  # fastest that reconciles (docs/SPEED.md)
TEXT_LAYER_NOTE = ("This page is a native PDF page: it is given below as its TEXT LAYER (printed rows top to bottom, "
                   "' | ' between columns) instead of an image. Read it exactly as you would read the page image.")
# Rows a bill prints to summarise its items (section subtotals, gross / grand total, net payable): kept for the
# reconciliation, never treated as charges.
SUMMARY_ROW = re.compile(r"\b(sub[\s-]?total|gross total|grand total|net payable|net amount|amount payable|total payable|"
                         r"bill total|balance due|amount due)\b|\btotal\s*$", re.I)
ITEM_TYPE_TO_CATEGORY = {"lab": LineCategory.LAB, "room": LineCategory.ROOM, "medical": LineCategory.MEDICAL,
                         "pharma": LineCategory.PHARMA, "surgery": LineCategory.SURGERY, "taxes": LineCategory.TAXES,
                         "professional fees": LineCategory.PROFESSIONAL_FEES, "services": LineCategory.SERVICES,
                         "radiology": LineCategory.RADIOLOGY, "icu": LineCategory.ICU}
Ask = Callable[..., ModelResult]


def doc_model() -> str:
    """The model that reads documents (LEAKLENS_DOC_MODEL); Kimi stays the fallback."""
    return os.environ.get("LEAKLENS_DOC_MODEL", DEFAULT_DOC_MODEL).strip() or DEFAULT_DOC_MODEL


def text_layer_enabled() -> bool:
    """LEAKLENS_TEXT_LAYER=0 sends every page as an image (the old path)."""
    return os.environ.get("LEAKLENS_TEXT_LAYER", "1").strip() not in ("0", "false", "no")


def _as_text(page: PageImage) -> bool:
    return bool(page.text) and text_layer_enabled()


def make_ask(cache_dir: Optional[Path], meter: Optional[CostMeter] = None, offline: bool = False) -> Ask:
    """A call_model bound to one claim's cache and cost meter, on the document model with Kimi as the fallback."""
    model = doc_model()
    fallbacks = [KIMI_MODEL] if model != KIMI_MODEL else None

    def ask(prompt: str, payload, images, schema, **kw) -> ModelResult:
        kw.setdefault("model", model)
        kw.setdefault("fallbacks", fallbacks)
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
        if all(_as_text(p) for p in chunk):
            body = "\n\n".join(f"{labels[i]}\n{TEXT_LAYER_NOTE}\n{p.text}" for i, p in enumerate(chunk))
            return ask("classify_pages", f"{intro}\n\n{body}", [], PageClassificationBatch,
                       tag=f"classify_p{first}-{last}_text", max_tokens=32768)
        return ask("classify_pages", intro, encode_for_request([p.image for p in chunk]), PageClassificationBatch,
                   tag=f"classify_p{first}-{last}", labels=labels, max_tokens=32768)

    predictions = [PagePrediction(p.source_file, p.page_in_file, i, "other_documents", 0.0) for i, p in enumerate(pages)]
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
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
    document_fact_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # fact -> {document_name, page}
    extracted_by: Optional[str] = None   # ai-text when every bill page was read from its text layer, else ai-vision
    model: Optional[str] = None
    read_seconds: float = 0.0


def _amount(text: Any) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(text or ""))
    return float(m.group(0).replace(",", "")) if m else None


def _date(text: Any) -> Optional[date]:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(text or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _file_jobs(name: str, doc_type: str, file_pages: List[PageImage], ask: Ask, claim_id: str) -> List[Callable[[], ModelResult]]:
    """One call per batch of a file (bills one page per request), with the default extraction configuration.
    A page with a text layer goes as text; a scan or photo as an image."""
    is_bill = doc_type in BILL_TYPES
    defaults = PAYLOAD_DEFAULTS.get(doc_type.upper()) or PAYLOAD_DEFAULTS["OTHER_DOCUMENTS"]

    def job(chunk: List[PageImage]) -> Callable[[], ModelResult]:
        def run() -> ModelResult:
            numbers = [p.page_in_file for p in chunk]
            payload = {"claim_id": claim_id, "stage": STAGE, "document_type": doc_type, "document_uuid": name, **defaults,
                       "page_numbers": numbers, "total_pages": len(file_pages), "pages_per_request": len(chunk)}
            prompt = "digitise_bill" if is_bill else "digitise_doc"
            tag = f"digitise_{Path(name).stem}_p{numbers[0]}-{numbers[-1]}"
            if all(_as_text(p) for p in chunk):
                payload["input_mode"] = TEXT_LAYER_NOTE
                payload["page_text_layer"] = {str(p.page_in_file): p.text for p in chunk}
                return ask(prompt, payload, [], FileDigitizationResponse, tag=f"{tag}_text", max_tokens=32768)
            return ask(prompt, payload, encode_for_request([p.image for p in chunk]), FileDigitizationResponse,
                       tag=tag, max_tokens=32768)
        return run

    size = BILL_PAGES_PER_REQUEST if is_bill else DOC_PAGES_PER_REQUEST
    return [job(chunk) for _, chunk in batches(file_pages, size)]


def digitise_file(name: str, doc_type: str, file_pages: List[PageImage], ask: Ask, claim_id: str) -> List[ModelResult]:
    """Every batch of one file, in parallel."""
    jobs = _file_jobs(name, doc_type, file_pages, ask, claim_id)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
        return list(pool.map(lambda run: run(), jobs))


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


def _fact_page(dumps: List[Dict[str, Any]], fact: str, value: str, pages_per_request: int) -> int:
    """The 1-based page whose answer carried this fact's value (the first batch that yields it), else page 1."""
    for index, dump in enumerate(dumps):
        found: Dict[str, str] = {}
        _facts_from_fields(merge_bill_document_data_from_batches([dump])["fields"], found)
        if found.get(fact) == value:
            return index * pages_per_request + 1
    return 1


def digitise_documents(pages: List[PageImage], confirmed: Dict[str, str], ask: Ask, *, claim_id: str,
                       provider_id: Optional[str] = None) -> DigitisedClaim:
    """confirmed: file name -> document type (after the human review). Returns master-ready lines and facts."""
    out = DigitisedClaim()
    started = time.monotonic()
    by_file: Dict[str, List[PageImage]] = {}
    for p in pages:
        by_file.setdefault(p.source_file, []).append(p)
    # Bills first so their header facts win; every page of every file in flight at once.
    order = sorted(by_file, key=lambda name: confirmed.get(name) not in BILL_TYPES)
    jobs = {name: _file_jobs(name, confirmed.get(name, "other_documents"), by_file[name], ask, claim_id) for name in order}
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
        futures = {name: [pool.submit(run) for run in runs] for name, runs in jobs.items()}
        results = {name: [f.result() for f in fs] for name, fs in futures.items()}
    out.read_seconds = round(time.monotonic() - started, 2)
    bill_pages = [p for name in order if confirmed.get(name) in BILL_TYPES for p in by_file[name]] or pages
    out.extracted_by = "ai-text" if all(_as_text(p) for p in bill_pages) else "ai-vision"
    serial = 0
    for name in order:
        file_results = results[name]
        out.calls.extend(file_results)
        dumps = [r.parsed.model_dump() for r in file_results]
        out.raw[name] = dumps
        footer = merge_bill_document_data_from_batches(dumps)
        before = set(out.document_facts)
        _facts_from_fields(footer["fields"], out.document_facts)
        size = BILL_PAGES_PER_REQUEST if confirmed.get(name) in BILL_TYPES else DOC_PAGES_PER_REQUEST
        for fact in set(out.document_facts) - before:
            out.document_fact_sources[fact] = {"document_name": name,
                                               "page": _fact_page(dumps, fact, out.document_facts[fact], size)}
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
    models = Counter(r.model for r in out.calls)
    out.model = models.most_common(1)[0][0] if models else None
    printed = _amount(out.document_facts.get("net_payable")) or _amount(out.document_facts.get("grand_total"))
    out.printed_total = printed
    if printed is not None and out.lines:
        total = round(sum(l.amount for l in out.lines) + sum(float(r.get("total_amount") or 0) for r in out.discount_rows), 2)
        out.reconciled = abs(total - printed) <= 1.0
    return out
