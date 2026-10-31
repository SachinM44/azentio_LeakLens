"""The HTTP surface. Every endpoint except /health needs X-API-Key; every mutating endpoint writes an audit row."""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.checks import recalculate_settlement
from core.schemas.classification import DOCUMENT_TYPES
from core.schemas.finding import Finding, FindingOriginal, FindingStatus
from core.schemas.master import ProductConfig

from backend import eval_summary
from backend.auth import require_api_key
from backend.documents import claim_documents, classify_claim_documents, digitise_claim_documents
from backend.graph import latest_run, paused_at, resume_run, start_run
from backend.ingest import IngestResult, ingest_files
from backend.investigation import comparison, related_claims
from backend.master import build_master_record, load_product
from backend.report import build_report, render_html
from backend.settings import get_settings
from backend.store import get_store, now_iso, to_doc
from backend.views import ClaimFilters, claim_detail, claim_list, classification_rows, dashboard, write_audit

logger = logging.getLogger(__name__)

public = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

REVIEW_STATUS = {"confirm": FindingStatus.CONFIRMED, "correct": FindingStatus.CORRECTED,
                 "false_positive": FindingStatus.DISMISSED, "request_evidence": FindingStatus.CLARIFICATION_REQUESTED,
                 "escalate": FindingStatus.ESCALATED, "accept_correction": FindingStatus.CORRECTION_ACCEPTED,
                 "dismiss": FindingStatus.DISMISSED, "clarify": FindingStatus.CLARIFICATION_REQUESTED}  # last two: legacy
# The review action in the investigator agent's vocabulary (confirm | dismiss | clarify), to tell an override.
AS_RECOMMENDATION = {"confirm": "confirm", "accept_correction": "confirm", "correct": "confirm", "false_positive": "dismiss",
                     "dismiss": "dismiss", "request_evidence": "clarify", "clarify": "clarify", "escalate": "escalate"}
ESCALATION_TARGETS = ("senior_reviewer", "siu")


class PageConfirmation(BaseModel):
    page_id: str = Field(..., description="<document_id>:<page>")
    document_type: str = Field(..., description="One of core/schemas/document_types.json")


class ReviewRequest(BaseModel):
    action: str = Field(..., description="confirm | false_positive | request_evidence | escalate | accept_correction | "
                                         "correct (legacy: dismiss | clarify)")
    reason: str = Field(default="", description="Why (required for false_positive and correct)")
    amount: Optional[float] = Field(default=None, ge=0, description="Corrected amount (action=correct)")
    note: str = Field(default="", description="Reviewer note")
    escalate_to: Optional[str] = Field(default=None, description="senior_reviewer | siu (action=escalate)")


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="The note")


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
        claim = get_store().get(collection="claims", doc_id=claim_id) or {}
        return {"run_id": None, "claim_id": claim_id, "status": "not_run", "steps": [],
                "cost_usd": round(float(claim.get("document_cost_usd") or 0.0), 5), "paused_at": None, "retrieval_mode": None}
    run.setdefault("retrieval_mode", None)
    return run


@router.post("/claims/{claim_id}/documents/classify")
def classify_documents(claim_id: str, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    """Model page classification over the claim's documents; predictions land in classification[] for the
    review console. A model failure keeps the file-name guesses and is reported, never hidden."""
    _claim_or_404(claim_id)
    store = get_store()
    error: Optional[str] = None
    cost = 0.0
    try:
        documents, cost = classify_claim_documents(store=store, claim_id=claim_id)
    except Exception as exc:
        logger.warning("page classification failed", extra={"claim_id": claim_id, "error": str(exc)})
        error = str(exc)
        documents = claim_documents(store=store, claim_id=claim_id)
    write_audit(store=store, actor=actor, action="documents_classify", claim_id=claim_id,
                details={"documents": len(documents), "cost_usd": round(cost, 5), "error": error})
    return {"claim_id": claim_id, "classified": error is None, "error": error, "cost_usd": round(cost, 5),
            "needs_classification_review": bool(documents), "classification": classification_rows(documents)}


@router.post("/claims/{claim_id}/classification/confirm")
def confirm_classification(claim_id: str, pages: List[PageConfirmation], actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    """Human gate 1: store the confirmed page types, digitise the documents, then continue the workflow."""
    _claim_or_404(claim_id)
    store = get_store()
    documents = {doc["document_id"]: doc for doc in claim_documents(store=store, claim_id=claim_id)}
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
    digitisation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        digitisation = digitise_claim_documents(store=store, claim_id=claim_id, documents=list(documents.values()))
    except Exception as exc:
        logger.warning("digitisation failed; continuing with the structured lines", extra={"claim_id": claim_id, "error": str(exc)})
        error = str(exc)
    claim = store.get(collection="claims", doc_id=claim_id) or {}
    claim["needs_classification_review"] = False
    claim["digitisation_error"] = error
    store.upsert(collection="claims", doc_id=claim_id, doc=claim)
    record = build_master_record(store=store, claim_id=claim_id)
    write_audit(store=store, actor=actor, action="classification_confirm", claim_id=claim_id,
                details={"pages": [page.model_dump() for page in pages], "digitised": digitisation is not None,
                         "document_lines": len(digitisation["document_lines"]) if digitisation else 0,
                         "reconciled": digitisation.get("reconciled") if digitisation else None, "error": error})
    if paused_at(claim_id) == "classification_gate":
        run_id = resume_run(claim_id=claim_id, payload=[page.model_dump() for page in pages], background=True)
    else:
        run_id = start_run(claim_id=claim_id, background=True)
    return {"claim_id": claim_id, "run_id": run_id, "classification": classification_rows(list(documents.values())),
            "digitised": digitisation is not None, "digitisation_error": error,
            "document_lines": len(digitisation["document_lines"]) if digitisation else 0,
            "document_facts": record.document_facts if record else {}, "printed_total": record.printed_total if record else None,
            "reconciled": record.reconciled if record else None, "source": claim.get("source")}


@router.post("/claims/{claim_id}/findings/{finding_id}/review")
def review_finding(claim_id: str, finding_id: str, body: ReviewRequest, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    store = get_store()
    if body.action not in REVIEW_STATUS:
        raise HTTPException(status_code=422, detail=f"action must be one of {' | '.join(REVIEW_STATUS)}")
    doc = store.get(collection="findings", doc_id=finding_id)
    if doc is None or doc.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"finding {finding_id} not found on claim {claim_id}")
    finding = Finding.model_validate(doc)
    reason = body.reason.strip()
    _validate_review(body=body, reason=reason, finding=finding)
    previous = finding.status
    now = datetime.now(timezone.utc)
    first_decision = finding.original is None
    if first_decision:  # what the system raised, frozen before any human changes it
        finding.original = FindingOriginal(amount=finding.amount, amount_kind=finding.amount_kind.value, status=previous.value,
                                           correction=finding.correction, recommendation=finding.recommendation,
                                           recommendation_note=finding.recommendation_note, captured_at=now)
    finding.status = REVIEW_STATUS[body.action]
    finding.reviewer_note = body.note
    finding.decision_reason = reason or body.note
    finding.corrected_amount = body.amount if body.action == "correct" else None
    finding.escalated_to = body.escalate_to if body.action == "escalate" else None
    finding.decided_by = actor
    finding.decided_at = now
    finding.decision_history.append({"ts": now.isoformat(), "by": actor, "action": body.action, "from_status": previous.value,
                                     "to_status": finding.status.value, "reason": finding.decision_reason,
                                     "amount": body.amount, "escalate_to": finding.escalated_to})
    store.upsert(collection="findings", doc_id=finding_id, doc=to_doc(finding))
    review = {"review_id": f"{finding_id}:{now_iso()}", "claim_id": claim_id, "finding_id": finding_id, "actor": actor,
              "action": body.action, "amount": body.amount, "note": body.note, "reason": finding.decision_reason,
              "escalate_to": finding.escalated_to, "from_status": previous.value, "to_status": finding.status.value, "ts": now_iso()}
    store.upsert(collection="reviews", doc_id=review["review_id"], doc=review)
    details: Dict[str, Any] = {"finding_id": finding_id, "check_id": finding.check_id.value, "action": body.action,
                               "from_status": previous.value, "to_status": finding.status.value,
                               "reason": finding.decision_reason, "amount": body.amount, "note": body.note,
                               "escalate_to": finding.escalated_to,
                               "overrides_recommendation": _overrides(body=body, finding=finding)}
    if first_decision:
        details["original"] = to_doc(finding.original)
    write_audit(store=store, actor=actor, action=f"review_{body.action}", claim_id=claim_id, details=details)
    run_id = None
    if paused_at(claim_id) == "review_gate":
        run_id = resume_run(claim_id=claim_id, payload={"finding_id": finding_id, "action": body.action})
    else:
        _recompute_settlement(claim_id=claim_id)
    detail = claim_detail(store=store, claim_id=claim_id) or {}
    return {"claim_id": claim_id, "run_id": run_id, "findings": detail.get("findings", []),
            "finding": next((f for f in detail.get("findings", []) if f["finding_id"] == finding_id), None),
            "settlement": detail.get("settlement"), "summary": detail.get("summary")}


def _validate_review(body: ReviewRequest, reason: str, finding: Finding) -> None:
    if body.action == "false_positive" and not reason:
        raise HTTPException(status_code=400, detail="A reason is required to mark a finding as a false positive")
    if body.action == "escalate" and body.escalate_to not in ESCALATION_TARGETS:
        raise HTTPException(status_code=400, detail="escalate_to must be senior_reviewer or siu")
    if body.action == "accept_correction" and finding.correction is None:
        raise HTTPException(status_code=400, detail="This finding has no recommended correction to accept")
    if body.action == "correct":
        if body.amount is None:  # 422 kept from the first version of this endpoint
            raise HTTPException(status_code=422, detail="action=correct needs an amount")
        if not (reason or body.note.strip()):
            raise HTTPException(status_code=400, detail="A reason is required to correct a finding")


def _overrides(body: ReviewRequest, finding: Finding) -> bool:
    """True when the analyst went against what the system proposed: a false positive, a different amount than the
    recommended correction, or an action other than the AI recommendation."""
    if body.action in ("false_positive", "dismiss"):
        return True
    if body.action == "correct":
        proposed = finding.correction.delta if finding.correction is not None else finding.amount
        if abs(float(body.amount or 0) - proposed) > 0.005:
            return True
    return bool(finding.recommendation) and AS_RECOMMENDATION[body.action] != finding.recommendation


# ----------------------------------------------------------------------------------------------- investigation


@router.post("/claims/{claim_id}/notes")
def add_note(claim_id: str, body: NoteRequest, actor: str = Depends(require_api_key)) -> Dict[str, Any]:
    _claim_or_404(claim_id)
    store = get_store()
    note = {"note_id": f"NOTE-{uuid.uuid4().hex[:12]}", "claim_id": claim_id, "author": actor, "ts": now_iso(),
            "text": body.text.strip()}
    store.upsert(collection="notes", doc_id=note["note_id"], doc=note)
    write_audit(store=store, actor=actor, action="note_added", claim_id=claim_id, details={"note_id": note["note_id"]})
    return note


@router.get("/claims/{claim_id}/related")
def get_related(claim_id: str) -> Dict[str, Any]:
    claim = _claim_or_404(claim_id)
    findings = get_store().list(collection="findings", filter_={"claim_id": claim_id})
    return {"claim_id": claim_id, "related": related_claims(store=get_store(), claim=claim, findings=findings)}


@router.get("/claims/{claim_id}/comparison")
def get_comparison(claim_id: str) -> Dict[str, Any]:
    return comparison(store=get_store(), claim=_claim_or_404(claim_id))


@router.get("/claims/{claim_id}/report")
def get_report(claim_id: str, format: str = Query(default="json", pattern="^(json|html)$"),
               actor: str = Depends(require_api_key)) -> Response:
    store = get_store()
    detail = claim_detail(store=store, claim_id=claim_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
    report = build_report(store=store, detail=detail, generated_by=actor)
    write_audit(store=store, actor=actor, action="report_generated", claim_id=claim_id, details={"format": format})
    if format == "html":
        return HTMLResponse(content=render_html(report=report))
    return JSONResponse(content=report, headers={"Content-Disposition": f'attachment; filename="investigation_{claim_id}.json"'})


def _recompute_settlement(claim_id: str) -> None:
    """No paused graph (claim not run, or run already finished): settle directly from the stored findings."""
    store = get_store()
    record = build_master_record(store=store, claim_id=claim_id)
    if record is None:
        return
    findings = [Finding.model_validate(doc) for doc in store.list(collection="findings", filter_={"claim_id": claim_id})]
    settlement = recalculate_settlement(record, findings)
    store.upsert(collection="settlements", doc_id=claim_id, doc=to_doc(settlement))
    if findings and not any(f.status in (FindingStatus.OPEN, FindingStatus.ESCALATED) for f in findings):
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
