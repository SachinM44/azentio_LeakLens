"""Builds the MasterRecord for one claim from the stored collections and keeps `master_records` fresh."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from core.schemas.master import Claim, HistoryRecord, InvoiceLine, MasterRecord, Policy, ProductConfig

from backend.store import Repository, to_doc

logger = logging.getLogger(__name__)


def default_product(product_id: str, currency: str = "INR") -> ProductConfig:
    """A placeholder config so a claim whose product was never configured still runs."""
    return ProductConfig(product_id=product_id, name=product_id, insurer="unconfigured", market="", currency=currency)


def load_product(store: Repository, product_id: str, currency: str = "INR") -> ProductConfig:
    doc = store.get(collection="products", doc_id=product_id)
    return ProductConfig.model_validate(doc) if doc else default_product(product_id=product_id, currency=currency)


def history_index(store: Repository) -> Dict[str, HistoryRecord]:
    """claim_id -> HistoryRecord for every earlier claim in the dataset (cross-claim checks read this)."""
    index: Dict[str, HistoryRecord] = {}
    for doc in store.list(collection="history"):
        try:
            record = HistoryRecord.model_validate(doc)
        except Exception as exc:  # a stored row never fails validation, but never crash a run over one
            logger.warning("history row skipped", extra={"claim_id": doc.get("claim_id"), "error": str(exc)})
            continue
        index[record.claim_id] = record
    return index


def claim_history(store: Repository, claim: Claim) -> List[HistoryRecord]:
    """Earlier claims of the same member or the same policy, excluding the claim itself."""
    rows: List[HistoryRecord] = []
    seen: set = set()
    for doc in store.list(collection="history"):
        if doc.get("claim_id") == claim.claim_id or doc.get("claim_id") in seen:
            continue
        if doc.get("claimant_id") == claim.claimant_id or doc.get("policy_number") == claim.policy_number:
            rows.append(HistoryRecord.model_validate(doc))
            seen.add(doc["claim_id"])
    rows.sort(key=lambda row: row.incident_date)
    return rows


def build_master_record(store: Repository, claim_id: str) -> Optional[MasterRecord]:
    """Assemble claim + lines + policy + product + history + documents and store it in master_records."""
    claim_doc = store.get(collection="claims", doc_id=claim_id)
    if claim_doc is None:
        return None
    claim = Claim.model_validate(claim_doc)
    lines = [InvoiceLine.model_validate(doc) for doc in store.list(collection="invoice_lines", filter_={"claim_id": claim_id})]
    lines.sort(key=lambda line: (line.invoice_no, line.serial_no))
    policy_doc = store.get(collection="policies", doc_id=claim.policy_number)
    policy = Policy.model_validate(policy_doc) if policy_doc else None
    product = load_product(store=store, product_id=claim.product_id, currency=claim.currency)
    documents = store.list(collection="documents", filter_={"claim_id": claim_id})
    documents.sort(key=lambda doc: doc.get("uploaded_at", ""))
    document_types = {doc["document_id"]: doc["document_type"] for doc in documents if doc.get("document_type")}
    record = MasterRecord(claim=claim, lines=lines, policy=policy, history=claim_history(store=store, claim=claim),
                          product=product, documents=[doc["document_id"] for doc in documents],
                          document_types=document_types)
    store.upsert(collection="master_records", doc_id=claim_id, doc=to_doc(record))
    return record


def refresh_master_records(store: Repository, claim_ids: List[str]) -> int:
    count = 0
    for claim_id in claim_ids:
        if build_master_record(store=store, claim_id=claim_id) is not None:
            count += 1
    return count
