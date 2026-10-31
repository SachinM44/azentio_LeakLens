"""The document path behind the API: stored documents -> page images -> page classification (model) -> human
confirmation -> digitisation -> master lines / document facts. Model spend is metered per claim and added to the
claim and its latest run.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.documents.pipeline import DigitisedClaim, classify_pages, digitise_documents, make_ask
from core.llm.client import CostMeter
from core.media.pages import PageImage, load_file_pages

from backend.graph import latest_run, start_run
from backend.settings import get_settings
from backend.store import Repository, now_iso, to_doc

logger = logging.getLogger(__name__)


def add_cost(store: Repository, claim_id: str, usd: float) -> None:
    """Model spend lands on the claim (document_cost_usd) and on its latest run (cost_usd), when there is one."""
    if usd <= 0:
        return
    claim = store.get(collection="claims", doc_id=claim_id)
    if claim is not None:
        claim["document_cost_usd"] = round(float(claim.get("document_cost_usd") or 0.0) + usd, 5)
        store.upsert(collection="claims", doc_id=claim_id, doc=claim)
    run = latest_run(store=store, claim_id=claim_id)
    if run is not None:
        run["cost_usd"] = round(float(run.get("cost_usd") or 0.0) + usd, 5)
        store.upsert(collection="runs", doc_id=run["run_id"], doc=run)


def claim_documents(store: Repository, claim_id: str) -> List[Dict[str, Any]]:
    docs = store.list(collection="documents", filter_={"claim_id": claim_id})
    docs.sort(key=lambda doc: doc.get("uploaded_at", ""))
    return docs


def load_claim_pages(store: Repository, claim_id: str, documents: List[Dict[str, Any]]) -> List[PageImage]:
    """Page images of every stored document; bytes are written under the claim's cache folder for the loader."""
    folder = get_settings().cache_dir_for(claim_id) / "pages"
    folder.mkdir(parents=True, exist_ok=True)
    pages: List[PageImage] = []
    seen_names = set()
    for doc in documents:
        data, name, _ = store.open_document(document_id=doc["document_id"])
        if name in seen_names:  # a second copy of the same file is not read twice
            continue
        seen_names.add(name)
        path = folder / name
        path.write_bytes(data)
        pages.extend(load_file_pages(path))
    return pages


def _meter() -> CostMeter:
    return CostMeter(cap_usd=get_settings().cost_cap_usd_per_claim)


def classify_claim_documents(store: Repository, claim_id: str) -> Tuple[List[Dict[str, Any]], float]:
    """Model predictions per page written into each document's classification list; returns (documents, cost)."""
    documents = claim_documents(store=store, claim_id=claim_id)
    if not documents:
        return documents, 0.0
    settings = get_settings()
    pages = load_claim_pages(store=store, claim_id=claim_id, documents=documents)
    meter = _meter()
    ask = make_ask(settings.cache_dir_for(claim_id), meter, offline=settings.documents_offline)
    predictions = classify_pages(pages, ask, bundle_name=f"{claim_id}.pdf")
    by_name = {doc["name"]: doc for doc in documents}
    for prediction in predictions:
        doc = by_name.get(prediction.source_file)
        if doc is None:
            continue
        page_id = f"{doc['document_id']}:{prediction.page_in_file}"
        entries = doc.setdefault("classification", [])
        entry = next((e for e in entries if e["page_id"] == page_id), None)
        if entry is None:
            entry = {"page_id": page_id, "page": prediction.page_in_file, "confirmed_type": None}
            entries.append(entry)
        entry.update({"predicted_type": prediction.document_type, "confidence": round(prediction.confidence, 3),
                      "predicted_by": "model"})
    for doc in documents:
        doc["classified_at"] = now_iso()
        store.upsert(collection="documents", doc_id=doc["document_id"], doc=doc)
    claim = store.get(collection="claims", doc_id=claim_id)
    if claim is not None:
        claim["needs_classification_review"] = True
        store.upsert(collection="claims", doc_id=claim_id, doc=claim)
    add_cost(store=store, claim_id=claim_id, usd=meter.spent_usd)
    logger.info("pages classified", extra={"claim_id": claim_id, "pages": len(pages), "cost_usd": meter.spent_usd})
    return documents, meter.spent_usd


def confirmed_types_by_name(documents: List[Dict[str, Any]]) -> Dict[str, str]:
    """File name -> confirmed type (the most common confirmed page type of the file)."""
    out: Dict[str, str] = {}
    for doc in documents:
        counts = Counter(e["confirmed_type"] for e in doc.get("classification", []) if e.get("confirmed_type"))
        if counts:
            out[doc["name"]] = counts.most_common(1)[0][0]
    return out


def digitise_claim_documents(store: Repository, claim_id: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run digitisation over the confirmed documents and apply the result:
    - no structured lines on the claim: the digitised lines become the master lines (claim.source = documents);
    - structured lines exist: they stay; the digitised lines are kept as document_lines for the Master data tab;
    - document facts, printed total and reconciliation always go to the master record (via `digitisations`)."""
    settings = get_settings()
    confirmed = confirmed_types_by_name(documents)
    claim = store.get(collection="claims", doc_id=claim_id) or {}
    pages = load_claim_pages(store=store, claim_id=claim_id, documents=documents)
    meter = _meter()
    ask = make_ask(settings.cache_dir_for(claim_id), meter, offline=settings.documents_offline)
    try:
        result: DigitisedClaim = digitise_documents(pages, confirmed, ask, claim_id=claim_id, provider_id=claim.get("provider_id"))
    finally:
        add_cost(store=store, claim_id=claim_id, usd=meter.spent_usd)
    id_by_name = {doc["name"]: doc["document_id"] for doc in documents}
    lines = []
    for line in result.lines:
        line.document_id = id_by_name.get(line.document_id or "", line.document_id)
        lines.append(to_doc(line))
    structured = [doc for doc in store.list(collection="invoice_lines", filter_={"claim_id": claim_id})
                  if not doc.get("document_id")]
    source = "mixed"
    if not structured:
        for doc in store.list(collection="invoice_lines", filter_={"claim_id": claim_id}):
            store.delete(collection="invoice_lines", doc_id=doc["line_id"])
        for doc in lines:
            store.upsert(collection="invoice_lines", doc_id=doc["line_id"], doc=doc)
        source = "documents"
    fact_sources = {fact: {"document_id": id_by_name.get(src["document_name"], src["document_name"]),
                           "document_name": src["document_name"], "page": src["page"]}
                    for fact, src in result.document_fact_sources.items()}
    stamp = now_iso()
    record = {"claim_id": claim_id, "ts": stamp, "document_facts": result.document_facts,
              "document_fact_sources": fact_sources, "extracted_by": result.extracted_by, "extracted_at": stamp,
              "model": result.model, "read_seconds": result.read_seconds, "pages_read": len(pages),
              "printed_total": result.printed_total, "reconciled": result.reconciled, "document_lines": lines,
              "discount_rows": result.discount_rows, "confirmed_types": confirmed, "cost_usd": round(meter.spent_usd, 5),
              "calls": len(result.calls)}
    store.upsert(collection="digitisations", doc_id=claim_id, doc=record)
    if claim:
        claim["source"] = source
        claim["needs_classification_review"] = False
        store.upsert(collection="claims", doc_id=claim_id, doc=claim)
    logger.info("documents digitised", extra={"claim_id": claim_id, "lines": len(lines), "source": source,
                                              "reconciled": result.reconciled, "cost_usd": meter.spent_usd})
    return record


AUTO_CONFIRM_CONFIDENCE = 0.85
_reading: Dict[str, threading.Lock] = {}
_reading_guard = threading.Lock()


def auto_confirmable(documents: List[Dict[str, Any]]) -> bool:
    """True when the model classified every page with confidence >= AUTO_CONFIRM_CONFIDENCE."""
    entries = [e for doc in documents for e in doc.get("classification", [])]
    return bool(entries) and all(e.get("predicted_by") == "model" and float(e.get("confidence") or 0) >= AUTO_CONFIRM_CONFIDENCE
                                 for e in entries)


def confirm_predicted_types(store: Repository, documents: List[Dict[str, Any]]) -> None:
    """The model's page types become the confirmed types (what the analyst's confirm would store)."""
    stamp = now_iso()
    for doc in documents:
        for entry in doc.get("classification", []):
            entry["confirmed_type"] = entry.get("predicted_type")
            entry["confirmed_by"] = "auto"
        confirmed = [e["confirmed_type"] for e in doc.get("classification", []) if e.get("confirmed_type")]
        if confirmed:
            doc["document_type"] = Counter(confirmed).most_common(1)[0][0]
            doc["confirmed_at"] = stamp
        store.upsert(collection="documents", doc_id=doc["document_id"], doc=doc)


def read_claim_documents(store: Repository, claim_id: str, progress: Optional[Any] = None) -> str:
    """Automatic reading: classify -> auto-confirm (every page >= 0.85, else wait for the analyst) -> read -> check.
    Claims with data lines keep them (the read lines go to `digitisations` for the comparison); document-only claims
    take the read lines and run the checks. Returns the outcome: no_documents | waiting_for_analyst | read | checked.
    progress(step, status, seconds) is told about each step."""
    def tell(step: str, status: str, seconds: float = 0.0) -> None:
        if progress is not None:
            progress(step, status, round(seconds, 2))

    with _reading_guard:
        lock = _reading.setdefault(claim_id, threading.Lock())
    with lock:
        documents = claim_documents(store=store, claim_id=claim_id)
        if not documents:
            return "no_documents"
        started = time.monotonic()
        tell("classify", "running")
        documents, _ = classify_claim_documents(store=store, claim_id=claim_id)
        tell("classify", "done", time.monotonic() - started)
        if not auto_confirmable(documents):
            tell("confirm", "waiting")
            return "waiting_for_analyst"
        confirm_predicted_types(store=store, documents=documents)
        tell("confirm", "done")
        started = time.monotonic()
        tell("read", "running")
        record = digitise_claim_documents(store=store, claim_id=claim_id, documents=documents)
        tell("read", "done", time.monotonic() - started)
        claim = store.get(collection="claims", doc_id=claim_id) or {}
        if claim.get("source") != "documents":
            return "read"
        started = time.monotonic()
        tell("check", "running")
        start_run(claim_id=claim_id, background=False)
        tell("check", "done", time.monotonic() - started)
        logger.info("claim read automatically", extra={"claim_id": claim_id, "lines": len(record.get("document_lines", []))})
        return "checked"


def read_in_background(store: Repository, claim_ids: List[str]) -> None:
    """Automatic reading of each claim's stored documents on a worker thread; a failure leaves the claim for the analyst."""
    def work() -> None:
        for claim_id in claim_ids:
            try:
                read_claim_documents(store=store, claim_id=claim_id)
            except Exception as exc:  # noqa: BLE001 - the classification gate still lets the analyst finish by hand
                logger.warning("automatic reading failed", extra={"claim_id": claim_id, "error": str(exc)})
    threading.Thread(target=work, daemon=True).start()
