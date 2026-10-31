"""Builds the MasterRecord for one claim from the stored collections and keeps `master_records` fresh.

Also the dataset-wide inputs the checks take beside the record: the history index, every other claim and the
peer invoice lines (duplicate-claim, related-party and provider-benchmark checks read across claims).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.master import Claim, HistoryRecord, InvoiceLine, MasterRecord, Policy, ProductConfig

from backend.settings import REPO_ROOT, get_settings
from backend.store import Repository, to_doc

logger = logging.getLogger(__name__)


def default_product(product_id: str, currency: str = "INR") -> ProductConfig:
    """A placeholder config so a claim whose product was never configured still runs."""
    return ProductConfig(product_id=product_id, name=product_id, insurer="unconfigured", market="", currency=currency)


def load_product(store: Repository, product_id: str, currency: str = "INR") -> ProductConfig:
    doc = store.get(collection="products", doc_id=product_id)
    return ProductConfig.model_validate(doc) if doc else default_product(product_id=product_id, currency=currency)


def _validated(model_cls: type, docs: List[Dict[str, Any]], label: str) -> list:
    """Stored rows passed validation at ingest; a bad one is logged and skipped, never crashes a run."""
    out = []
    for doc in docs:
        try:
            out.append(model_cls.model_validate(doc))
        except Exception as exc:
            logger.warning("stored row skipped", extra={"entity": label, "row_id": doc.get("claim_id") or doc.get("line_id"), "error": str(exc)})
    return out


def history_index(store: Repository) -> Dict[str, HistoryRecord]:
    """claim_id -> HistoryRecord for every earlier claim in the dataset (cross-claim checks read this)."""
    return {record.claim_id: record for record in _validated(HistoryRecord, store.list(collection="history"), "history")}


def other_claims(store: Repository, claim_id: str) -> List[Claim]:
    """Every other claim currently ingested (duplicate-claim and related-party patterns)."""
    docs = [doc for doc in store.list(collection="claims") if doc.get("claim_id") != claim_id]
    return _validated(Claim, docs, "claims")


def peer_lines(store: Repository, claim_id: str) -> List[InvoiceLine]:
    """Every invoice line in the store except this claim's (provider price benchmarking)."""
    docs = [doc for doc in store.list(collection="invoice_lines") if doc.get("claim_id") != claim_id]
    return _validated(InvoiceLine, docs, "invoice_lines")


def claim_history(store: Repository, claim: Claim) -> List[HistoryRecord]:
    """Earlier claims of the same member or the same policy, excluding the claim itself."""
    docs = [doc for doc in store.list(collection="history")
            if doc.get("claim_id") != claim.claim_id
            and (doc.get("claimant_id") == claim.claimant_id or doc.get("policy_number") == claim.policy_number)]
    rows = _validated(HistoryRecord, docs, "history")
    rows.sort(key=lambda row: row.incident_date)
    return rows


# ----------------------------------------------------------------------------------------------- documents manifest


@dataclass
class ManifestDocument:
    """One document the manifest says was submitted with a claim; `path` is set when a file was rendered."""
    document_id: str
    document_type: str
    name: Optional[str]
    path: Optional[Path]


@dataclass
class ManifestEntry:
    claim_id: str
    documents: List[ManifestDocument] = field(default_factory=list)
    document_facts: Dict[str, str] = field(default_factory=dict)


_MANIFEST_CACHE: Dict[str, Tuple[float, Dict[str, ManifestEntry]]] = {}  # path -> (mtime, entries)


def _manifest_document(raw: Dict[str, Any], root: Path) -> Optional[ManifestDocument]:
    doc_type = raw.get("document_type") or raw.get("type")
    document_id = raw.get("document_id") or raw.get("id")
    if not doc_type or not document_id:
        return None
    file_ = raw.get("file") or raw.get("name") or raw.get("filename")
    path = (root / str(file_)) if file_ else None
    return ManifestDocument(document_id=str(document_id), document_type=str(doc_type),
                            name=Path(str(file_)).name if file_ else None, path=path)


def manifest_entries(path: Path) -> Dict[str, ManifestEntry]:
    """claim_id -> ManifestEntry from the synthetic documents manifest ({"documents_root", "claims": [...]}; a
    bare list or {claim_id: entry} dict is accepted too). Parsed once per file version: a refresh of every claim
    must not re-read the file per claim."""
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    cached = _MANIFEST_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("documents manifest unreadable", extra={"path": str(path), "error": str(exc)})
        return {}
    root = path.parent
    if isinstance(payload, dict) and payload.get("documents_root"):
        declared = Path(str(payload["documents_root"]))
        root = declared if declared.is_absolute() else REPO_ROOT / declared
    if isinstance(payload, dict) and isinstance(payload.get("claims"), (list, dict)):
        payload = payload["claims"]
    raw_entries: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        raw_entries = [entry for entry in payload if isinstance(entry, dict) and entry.get("claim_id")]
    elif isinstance(payload, dict):
        raw_entries = [{**entry, "claim_id": claim_id} for claim_id, entry in payload.items() if isinstance(entry, dict)]
    entries: Dict[str, ManifestEntry] = {}
    for raw in raw_entries:
        facts_raw = raw.get("document_facts") if isinstance(raw.get("document_facts"), dict) else {}
        facts = {str(key): str(value) for key, value in facts_raw.items() if value is not None and str(value) != ""}
        docs = [_manifest_document(raw=item, root=root) for item in raw.get("documents", []) if isinstance(item, dict)]
        entries[str(raw["claim_id"])] = ManifestEntry(claim_id=str(raw["claim_id"]), document_facts=facts,
                                                      documents=[doc for doc in docs if doc is not None])
    _MANIFEST_CACHE[str(path)] = (mtime, entries)
    return entries


def manifest_for_claim(claim_id: str) -> Optional[ManifestEntry]:
    return manifest_entries(path=get_settings().documents_manifest_abs).get(claim_id)


def _printed_total(facts: Dict[str, str]) -> Optional[float]:
    raw = facts.get("net_payable") or facts.get("printed_total") or facts.get("total")
    if not raw:
        return None
    try:
        return float(str(raw).replace(",", "").replace("₹", "").strip())
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- master record


def build_master_record(store: Repository, claim_id: str, persist: bool = True) -> Optional[MasterRecord]:
    """Assemble claim + lines + policy + product + history + documents (+ facts) and store it in master_records
    (persist=False returns the record and its storable dict without writing, for bulk refreshes)."""
    built = _build(store=store, claim_id=claim_id)
    if built is None:
        return None
    record, stored = built
    if persist:
        store.upsert(collection="master_records", doc_id=claim_id, doc=stored)
    return record


def _build(store: Repository, claim_id: str) -> Optional[Tuple[MasterRecord, Dict[str, Any]]]:
    claim_doc = store.get(collection="claims", doc_id=claim_id)
    if claim_doc is None:
        return None
    claim = Claim.model_validate(claim_doc)
    lines = _validated(InvoiceLine, store.list(collection="invoice_lines", filter_={"claim_id": claim_id}), "invoice_lines")
    lines.sort(key=lambda line: (line.invoice_no, line.serial_no))
    policy_doc = store.get(collection="policies", doc_id=claim.policy_number)
    policy = Policy.model_validate(policy_doc) if policy_doc else None
    product = load_product(store=store, product_id=claim.product_id, currency=claim.currency)
    documents = store.list(collection="documents", filter_={"claim_id": claim_id})
    documents.sort(key=lambda doc: doc.get("uploaded_at", ""))
    manifest = manifest_for_claim(claim_id=claim_id)
    manifest_docs = manifest.documents if manifest else []
    facts = dict(manifest.document_facts) if manifest else {}
    type_by_name = {doc.name: doc.document_type for doc in manifest_docs if doc.name}
    # Stored documents first (confirmed type, else what the manifest says about that file), then the manifest's
    # documents that were never uploaded or rendered: the evidence check needs every submitted document's type.
    document_ids: List[str] = []
    document_types: Dict[str, str] = {}
    stored_names = set()
    for doc in documents:
        document_ids.append(doc["document_id"])
        stored_names.add(doc.get("name"))
        doc_type = doc.get("document_type") or type_by_name.get(doc.get("name"))
        if doc_type:
            document_types[doc["document_id"]] = doc_type
    for doc in manifest_docs:
        if (doc.name and doc.name in stored_names) or doc.document_id in document_ids:
            continue
        document_ids.append(doc.document_id)
        document_types[doc.document_id] = doc.document_type
    if document_ids and claim.source == "structured":
        claim.source = "mixed"
        claim_doc["source"] = "mixed"
        store.upsert(collection="claims", doc_id=claim_id, doc=claim_doc)
    printed_total = _printed_total(facts=facts)
    reconciled = None if printed_total is None else abs(round(sum(line.amount for line in lines), 2) - printed_total) <= 1.0
    digitised = store.get(collection="digitisations", doc_id=claim_id) or {}  # the document path, once it has run
    if digitised:
        facts = {**facts, **{k: str(v) for k, v in (digitised.get("document_facts") or {}).items()}}
        if digitised.get("printed_total") is not None:
            printed_total = float(digitised["printed_total"])
            reconciled = digitised.get("reconciled")
    record = MasterRecord(claim=claim, lines=lines, policy=policy, history=claim_history(store=store, claim=claim),
                          product=product, documents=document_ids, document_types=document_types,
                          document_facts=facts, printed_total=printed_total, reconciled=reconciled)
    stored = {**to_doc(record), "document_lines": digitised.get("document_lines", []),
              "discount_rows": digitised.get("discount_rows", [])}
    return record, stored


def refresh_master_records(store: Repository, claim_ids: List[str]) -> int:
    """Rebuild many master records with one write (ingest refreshes every claim after a policy / history load)."""
    docs: Dict[str, Dict[str, Any]] = {}
    for claim_id in claim_ids:
        built = _build(store=store, claim_id=claim_id)
        if built is not None:
            docs[claim_id] = built[1]
    return store.bulk_upsert(collection="master_records", docs=docs)
