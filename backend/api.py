"""The HTTP surface. Every endpoint except /health needs X-API-Key; every mutating endpoint writes an audit row."""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.checks import recalculate_settlement
from core.schemas.classification import DOCUMENT_TYPES
from core.schemas.finding import Finding, FindingStatus
from core.schemas.master import ProductConfig

from backend import eval_summary
from backend.auth import require_api_key
from backend.graph import latest_run, paused_at, resume_run, start_run
from backend.ingest import IngestResult, ingest_files
from backend.master import build_master_record, load_product
from backend.settings import get_settings
from backend.store import get_store, now_iso, to_doc
from backend.views import ClaimFilters, claim_detail, claim_list, classification_rows, dashboard, write_audit

logger = logging.getLogger(__name__)

public = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

REVIEW_STATUS = {"confirm": FindingStatus.CONFIRMED, "correct": FindingStatus.CORRECTED,
                 "dismiss": FindingStatus.DISMISSED, "clarify": FindingStatus.CLARIFICATION_REQUESTED}


class PageConfirmation(BaseModel):
    page_id: str = Field(..., description="<document_id>:<page>")
    document_type: str = Field(..., description="One of core/schemas/document_types.json")


class ReviewRequest(BaseModel):
    action: str = Field(..., description="confirm | correct | dismiss | clarify")
    amount: Optional[float] = Field(default=None, ge=0, description="Corrected amount (action=correct)")
    note: str = Field(default="", description="Reviewer note")


def _filters(type: Optional[str] = None, provider: Optional[str] = None, category: Optional[str] = None,
             min_amount: Optional[float] = None, max_amount: Optional[float] = None,
             from_: Optional[str] = Query(default=None, alias="from"), to: Optional[str] = None,
             status: Optional[str] = None) -> ClaimFilters:
    return ClaimFilters(type=type, provider=provider, category=category, min_amount=min_amount, max_amount=max_amount,
                        from_date=from_, to_date=to, status=status)


def _claim_or_404(claim_id: str) -> Dict[str, Any]:
    claim = get_store().get(collection="claims", doc_id=claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
    return claim


# ----------------------------------------------------------------------------------------------- public


@public.get("/health")
def health() -> Dict[str, Any]:
    settings = get_settings()
    return {"status": "ok", "store": "mongodb" if settings.mongodb_uri else "json-files", "ts": now_iso()}


# ----------------------------------------------------------------------------------------------- ingest


@router.post("/ingest", response_model=IngestResult)
async def ingest(files: List[UploadFile] = File(...), actor: str = Depends(require_api_key)) -> IngestResult:
    payload = [(upload.filename or "upload", await upload.read()) for upload in files]
    result = ingest_files(store=get_store(), files=payload, actor=actor)
    write_audit(store=get_store(), actor=actor, action="ingest", claim_id=None,
                details={"batch_id": result.batch_id, "files": [name for name, _ in payload], "counts": result.counts,
                         "claims_created": result.claims_created, "issues": len(result.validation)})
    return result


# ----------------------------------------------------------------------------------------------- claims


@router.get("/claims")
def list_claims(filters: ClaimFilters = Depends(_filters)) -> List[Dict[str, Any]]:
    return claim_list(store=get_store(), filters=filters)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str) -> Dict[str, Any]:
    detail = claim_detail(store=get_store(), claim_id=claim_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
    return detail


@router.post("/claims/{claim_id}/run")
def run_claim(claim_id: str, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    run_id = start_run(claim_id=claim_id, background=True)
    write_audit(store=get_store(), actor=actor, action="run", claim_id=claim_id, details={"run_id": run_id})
    return {"run_id": run_id, "claim_id": claim_id, "status": "queued"}


@router.get("/claims/{claim_id}/run")
def get_run(claim_id: str) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    run = latest_run(store=get_store(), claim_id=claim_id)
    if run is None:
        return {"run_id": None, "claim_id": claim_id, "status": "not_run", "steps": [], "cost_usd": 0.0, "paused_at": None}
    return run


@router.post("/claims/{claim_id}/classification/confirm")
def confirm_classification(claim_id: str, pages: List[PageConfirmation], actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    store = get_store()
    documents = {doc["document_id"]: doc for doc in store.list(collection="documents", filter_={"claim_id": claim_id})}
    for page in pages:
        if page.document_type not in DOCUMENT_TYPES:
            raise HTTPException(status_code=422, detail=f"unknown document_type '{page.document_type}'")
        document_id = page.page_id.rsplit(":", 1)[0]
        doc = documents.get(document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"page {page.page_id} is not on claim {claim_id}")
        for entry in doc.get("classification", []):
            if entry["page_id"] == page.page_id:
                entry["confirmed_type"] = page.document_type
    for doc in documents.values():
        confirmed = [entry["confirmed_type"] for entry in doc.get("classification", []) if entry.get("confirmed_type")]
        if confirmed:
            doc["document_type"] = confirmed[0]
            doc["confirmed_at"] = now_iso()
        store.upsert(collection="documents", doc_id=doc["document_id"], doc=doc)
    build_master_record(store=store, claim_id=claim_id)
    write_audit(store=store, actor=actor, action="classification_confirm", claim_id=claim_id,
                details={"pages": [page.model_dump() for page in pages]})
    run_id = None
    if paused_at(claim_id) == "classification_gate":
        run_id = resume_run(claim_id=claim_id, payload=[page.model_dump() for page in pages], background=True)
    return {"claim_id": claim_id, "classification": classification_rows(list(documents.values())), "run_id": run_id}


@router.post("/claims/{claim_id}/findings/{finding_id}/review")
def review_finding(claim_id: str, finding_id: str, body: ReviewRequest, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    store = get_store()
    if body.action not in REVIEW_STATUS:
        raise HTTPException(status_code=422, detail="action must be confirm | correct | dismiss | clarify")
    doc = store.get(collection="findings", doc_id=finding_id)
    if doc is None or doc.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"finding {finding_id} not found on claim {claim_id}")
    if body.action == "correct" and body.amount is None:
        raise HTTPException(status_code=422, detail="action=correct needs an amount")
    finding = Finding.model_validate(doc)
    previous = finding.status
    finding.status = REVIEW_STATUS[body.action]
    finding.reviewer_note = body.note
    finding.corrected_amount = body.amount if body.action == "correct" else None
    store.upsert(collection="findings", doc_id=finding_id, doc=to_doc(finding))
    review = {"review_id": f"{finding_id}:{now_iso()}", "claim_id": claim_id, "finding_id": finding_id, "actor": actor,
              "action": body.action, "amount": body.amount, "note": body.note, "from_status": previous.value,
              "to_status": finding.status.value, "ts": now_iso()}
    store.upsert(collection="reviews", doc_id=review["review_id"], doc=review)
    write_audit(store=store, actor=actor, action=f"review_{body.action}", claim_id=claim_id,
                details={"finding_id": finding_id, "check_id": finding.check_id.value, "amount": body.amount,
                         "note": body.note, "from_status": previous.value, "to_status": finding.status.value})
    run_id = None
    if paused_at(claim_id) == "review_gate":
        run_id = resume_run(claim_id=claim_id, payload={"finding_id": finding_id, "action": body.action})
    else:
        _recompute_settlement(claim_id=claim_id)
    detail = claim_detail(store=store, claim_id=claim_id) or {}
    return {"claim_id": claim_id, "run_id": run_id, "findings": detail.get("findings", []),
            "settlement": detail.get("settlement"), "summary": detail.get("summary")}


def _recompute_settlement(claim_id: str) -> None:
    """No paused graph (claim not run, or run already finished): settle directly from the stored findings."""
    store = get_store()
    record = build_master_record(store=store, claim_id=claim_id)
    if record is None:
        return
    findings = [Finding.model_validate(doc) for doc in store.list(collection="findings", filter_={"claim_id": claim_id})]
    settlement = recalculate_settlement(record, findings)
    store.upsert(collection="settlements", doc_id=claim_id, doc=to_doc(settlement))
    if findings and not any(f.status == FindingStatus.OPEN for f in findings):
        claim = store.get(collection="claims", doc_id=claim_id)
        if claim and claim.get("status") in ("checked", "reviewed"):
            claim["status"] = "reviewed"
            store.upsert(collection="claims", doc_id=claim_id, doc=claim)


# ----------------------------------------------------------------------------------------------- dashboard / config


@router.get("/dashboard")
def get_dashboard(filters: ClaimFilters = Depends(_filters)) -> Dict[str, Any]:
    return dashboard(store=get_store(), filters=filters)


@router.get("/config/{product_id}")
def get_config(product_id: str) -> Dict[str, Any]:
    return load_product(store=get_store(), product_id=product_id).model_dump(mode="json")


@router.get("/config")
def list_config() -> List[Dict[str, Any]]:
    return get_store().list(collection="products")


@router.put("/config/{product_id}")
def put_config(product_id: str, config: ProductConfig, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    config.product_id = product_id
    store = get_store()
    previous = store.get(collection="products", doc_id=product_id)
    doc = to_doc(config)
    store.upsert(collection="products", doc_id=product_id, doc=doc)
    changed = sorted(key for key in doc if previous is None or previous.get(key) != doc[key])
    write_audit(store=store, actor=actor, action="config_update", claim_id=None,
                details={"product_id": product_id, "changed_fields": changed, "created": previous is None})
    return doc


# ----------------------------------------------------------------------------------------------- documents / eval / audit


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> StreamingResponse:
    try:
        data, name, mime = get_store().open_document(document_id=document_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    headers = {"Content-Disposition": f'inline; filename="{name}"', "Content-Length": str(len(data))}
    return StreamingResponse(io.BytesIO(data), media_type=mime, headers=headers)


@router.get("/eval/summary")
def get_eval_summary() -> Dict[str, Any]:
    return eval_summary.summary(store=get_store(), key_path=get_settings().answer_key_abs)


@router.get("/audit")
def get_audit(claim_id: Optional[str] = None, limit: int = Query(default=500, ge=1, le=5000)) -> List[Dict[str, Any]]:
    rows = get_store().list(collection="audit", filter_={"claim_id": claim_id} if claim_id else None)
    rows.sort(key=lambda row: row["ts"], reverse=True)
    return rows[:limit]
