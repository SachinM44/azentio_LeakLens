"""Customer portal (contract section 7): a customer submits a claim with its documents, gets a claim id in about a
second, and follows a customer-safe status (no findings) while the documents are read and the claim is checked in
the background: classify -> auto-confirm (every page >= 0.85, else the analyst confirms) -> read -> check.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.auth import require_api_key
from backend.documents import claim_documents, read_claim_documents, read_in_background
from backend.graph import latest_run
from backend.ingest import store_document
from backend.master import refresh_master_records
from backend.settings import get_settings
from backend.store import Repository, get_store, now_iso

logger = logging.getLogger(__name__)
portal_router = APIRouter(dependencies=[Depends(require_api_key)])

CLAIM_TYPES = ("inpatient", "outpatient", "daycare", "pharmacy")
FILE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILES = 10
MAX_FILE_BYTES = 10 * 1024 * 1024
CLAIM_PREFIX = "CLM-P-"
STEPS = (("received", "Claim received"), ("classify", "Sorting your documents"), ("confirm", "Checking the document types"),
         ("read", "Reading your bill"), ("check", "Checking your claim"))
MESSAGES = {"received": "We have your claim and documents.",
            "reading_documents": "We are reading your documents.",
            "waiting_for_analyst": "A claims officer is confirming your documents.",
            "checking": "We are checking your claim against your policy.",
            "under_review": "A claims officer is reviewing your claim.",
            "settled": "Your claim has been decided.",
            "failed": "We could not read your documents automatically; a claims officer will follow up."}
_id_lock = threading.Lock()


def _problem(field: str, problem: str) -> Dict[str, str]:
    return {"field": field, "problem": problem}


def _parse_date(value: Optional[str], field: str, required: bool, problems: List[Dict[str, str]]) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        if required:
            problems.append(_problem(field, "required"))
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        problems.append(_problem(field, "not a date in the form YYYY-MM-DD"))
        return None


def _match_provider(store: Repository, typed: str) -> tuple:
    """(provider_id, provider_name) of a known provider whose name matches the typed one, else (None, typed)."""
    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    wanted = norm(typed)
    for doc in store.list(collection="providers"):
        name = str(doc.get("name") or doc.get("provider_name") or "")
        if name and norm(name) == wanted:
            return doc.get("provider_id"), name
    for doc in store.list(collection="claims"):
        if doc.get("provider_name") and norm(str(doc["provider_name"])) == wanted and doc.get("provider_id"):
            return doc["provider_id"], doc["provider_name"]
    return None, typed


def _next_claim_id(store: Repository) -> str:
    numbers = [int(doc["claim_id"][len(CLAIM_PREFIX):]) for doc in store.list(collection="claims")
               if str(doc.get("claim_id", "")).startswith(CLAIM_PREFIX) and doc["claim_id"][len(CLAIM_PREFIX):].isdigit()]
    return f"{CLAIM_PREFIX}{(max(numbers) if numbers else 0) + 1:04d}"


def _set_step(store: Repository, claim_id: str, step: str, status: str, seconds: float = 0.0,
              portal_status: Optional[str] = None) -> None:
    doc = store.get(collection="portal_claims", doc_id=claim_id)
    if doc is None:
        return
    for row in doc["steps"]:
        if row["name"] == step:
            row["status"] = status
            if seconds:
                row["seconds"] = seconds
    if portal_status:
        doc["status"] = portal_status
    doc["updated_at"] = now_iso()
    store.upsert(collection="portal_claims", doc_id=claim_id, doc=doc)


def process_portal_claim(claim_id: str) -> None:
    """The background pipeline for one portal claim; the portal record tracks each step."""
    store = get_store()
    step_status = {"classify": "reading_documents", "read": "reading_documents", "check": "checking"}

    def progress(step: str, status: str, seconds: float) -> None:
        portal_status = "waiting_for_analyst" if status == "waiting" else (step_status.get(step) if status == "running" else None)
        _set_step(store=store, claim_id=claim_id, step=step, status=status, seconds=seconds, portal_status=portal_status)

    try:
        outcome = read_claim_documents(store=store, claim_id=claim_id, progress=progress)
        refresh_master_records(store=store, claim_ids=[claim_id])
    except Exception as exc:  # noqa: BLE001 - the customer sees a safe message; the analyst can still finish by hand
        logger.warning("portal claim pipeline failed", extra={"claim_id": claim_id, "error": str(exc)})
        doc = store.get(collection="portal_claims", doc_id=claim_id) or {}
        for row in doc.get("steps", []):
            if row["status"] == "running":
                row["status"] = "failed"
        doc.update({"status": "failed", "error": str(exc)[:300], "updated_at": now_iso()})
        store.upsert(collection="portal_claims", doc_id=claim_id, doc=doc)
        return
    if outcome != "waiting_for_analyst":
        doc = store.get(collection="portal_claims", doc_id=claim_id) or {}
        doc.update({"status": _status_from_run(store=store, claim_id=claim_id) or "under_review", "updated_at": now_iso()})
        store.upsert(collection="portal_claims", doc_id=claim_id, doc=doc)


def _status_from_run(store: Repository, claim_id: str) -> Optional[str]:
    claim = store.get(collection="claims", doc_id=claim_id) or {}
    if claim.get("status") == "settled":
        return "settled"
    run = latest_run(store=store, claim_id=claim_id)
    if run is None:
        return None
    return {"completed": "settled", "paused": "under_review", "running": "checking", "queued": "checking",
            "failed": "failed"}.get(run.get("status"))


@portal_router.post("/portal/claims", status_code=201)
async def submit_claim(policy_number: Optional[str] = Form(default=None), member_id: Optional[str] = Form(default=None),
                       claim_type: Optional[str] = Form(default=None), incident_date: Optional[str] = Form(default=None),
                       admission_date: Optional[str] = Form(default=None), discharge_date: Optional[str] = Form(default=None),
                       provider_name: Optional[str] = Form(default=None), amount_claimed: Optional[str] = Form(default=None),
                       diagnosis: Optional[str] = Form(default=None), phone: Optional[str] = Form(default=None),
                       files: List[UploadFile] = File(default=[])) -> Any:
    """Validate, store the claim and its files, answer 201 at once; reading and checking run in the background."""
    store = get_store()
    problems: List[Dict[str, str]] = []
    policy = None
    number = (policy_number or "").strip()
    if not number:
        problems.append(_problem("policy_number", "required"))
    else:
        policy = store.get(collection="policies", doc_id=number)
        if policy is None:
            problems.append(_problem("policy_number", "unknown policy"))
    member = (member_id or "").strip()
    if not member:
        problems.append(_problem("member_id", "required"))
    elif policy is not None and member not in (policy.get("members") or []):
        problems.append(_problem("member_id", "member is not covered by this policy"))
    kind = (claim_type or "").strip().lower()
    if kind not in CLAIM_TYPES:
        problems.append(_problem("claim_type", f"must be one of {', '.join(CLAIM_TYPES)}"))
    incident = _parse_date(incident_date, "incident_date", True, problems)
    admitted = _parse_date(admission_date, "admission_date", False, problems)
    discharged = _parse_date(discharge_date, "discharge_date", False, problems)
    if admitted and discharged and discharged < admitted:
        problems.append(_problem("discharge_date", "is before the admission date"))
    if not (provider_name or "").strip():
        problems.append(_problem("provider_name", "required"))
    amount = None
    try:
        amount = float(str(amount_claimed or "").replace(",", "").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        problems.append(_problem("amount_claimed", "required, a number above 0"))
    uploads: List[tuple] = []
    real_files = [f for f in files if f is not None and (f.filename or "")]
    if not real_files:
        problems.append(_problem("files", "at least one file is required"))
    elif len(real_files) > MAX_FILES:
        problems.append(_problem("files", f"at most {MAX_FILES} files"))
    for upload in real_files[:MAX_FILES]:
        name = Path(upload.filename or "file").name
        data = await upload.read()
        if Path(name).suffix.lower() not in FILE_SUFFIXES:
            problems.append(_problem("files", f"{name}: only PDF, JPG or PNG files"))
        elif len(data) > MAX_FILE_BYTES:
            problems.append(_problem("files", f"{name}: larger than 10 MB"))
        elif not data:
            problems.append(_problem("files", f"{name}: the file is empty"))
        else:
            uploads.append((name, data))
    if problems:
        return JSONResponse(status_code=422, content={"detail": problems})

    provider_id, provider = _match_provider(store=store, typed=provider_name.strip())
    named = next((doc.get("claimant_name") for doc in store.list(collection="claims", filter_={"claimant_id": member})
                  if doc.get("claimant_name")), "")
    stamp = now_iso()
    with _id_lock:
        claim_id = _next_claim_id(store=store)
        claim = {"claim_id": claim_id, "policy_number": number, "product_id": policy["product_id"], "claimant_id": member,
                 "claimant_name": named, "provider_id": provider_id or f"PRV-PORTAL-{claim_id[len(CLAIM_PREFIX):]}",
                 "provider_name": provider, "claim_type": kind, "incident_date": incident.isoformat(),
                 "admission_date": admitted.isoformat() if admitted else None,
                 "discharge_date": discharged.isoformat() if discharged else None,
                 "diagnosis": (diagnosis or "").strip() or None, "requested_amount": amount, "proposed_settlement": None,
                 "currency": policy.get("currency") or "INR", "invoice_numbers": [],
                 "submitted_at": datetime.now().replace(microsecond=0).isoformat(),  # naive, like the ingested claims
                 "status": "ingested", "source": "documents", "contact_phone": (phone or "").strip() or None,
                 "extra": {"channel": "portal", "provider_matched": "yes" if provider_id else "no"}, "updated_at": stamp}
        store.upsert(collection="claims", doc_id=claim_id, doc=claim)
    seen: Dict[str, int] = {}
    for name, data in uploads:
        seen[name] = seen.get(name, 0) + 1
        stored_name = name if seen[name] == 1 else f"{Path(name).stem}_{seen[name]}{Path(name).suffix}"
        meta, _ = store_document(store=store, name=stored_name, data=data, claim_ids={claim_id})
        meta["claim_id"] = claim_id
        store.upsert(collection="documents", doc_id=meta["document_id"], doc=meta)
    steps = [{"name": name, "label": label, "status": "done" if name == "received" else "pending", "seconds": 0.0}
             for name, label in STEPS]
    store.upsert(collection="portal_claims", doc_id=claim_id,
                 doc={"claim_id": claim_id, "status": "received", "steps": steps, "created_at": stamp, "updated_at": stamp})
    refresh_master_records(store=store, claim_ids=[claim_id])
    threading.Thread(target=process_portal_claim, kwargs={"claim_id": claim_id}, daemon=True).start()
    logger.info("portal claim received", extra={"claim_id": claim_id, "files": len(uploads)})
    return {"claim_id": claim_id, "status": "received", "status_url": f"/portal/claims/{claim_id}"}


@portal_router.get("/portal/claims/{claim_id}")
def claim_status(claim_id: str) -> Dict[str, Any]:
    """Customer-safe status: steps with seconds, documents, what was read; never the findings."""
    store = get_store()
    doc = store.get(collection="portal_claims", doc_id=claim_id)
    claim = store.get(collection="claims", doc_id=claim_id)
    if doc is None or claim is None:
        raise HTTPException(status_code=404, detail=f"portal claim {claim_id} not found")
    status = doc.get("status", "received")
    if status in ("waiting_for_analyst", "under_review", "checking"):
        status = _status_from_run(store=store, claim_id=claim_id) or status
    digitisation = store.get(collection="digitisations", doc_id=claim_id) or {}
    documents = []
    for item in claim_documents(store=store, claim_id=claim_id):
        types = [e.get("confirmed_type") or e.get("predicted_type") for e in item.get("classification", [])]
        documents.append({"name": item.get("name"), "pages": item.get("pages"),
                          "type": item.get("document_type") or (max(set(types), key=types.count) if types else None)})
    steps = [dict(row) for row in doc.get("steps", [])]
    if status in ("under_review", "settled"):
        for row in steps:
            if row["name"] == "check" and row["status"] != "done":
                row["status"] = "done"
    return {"claim_id": claim_id, "status": status, "steps": steps, "documents": documents,
            "pages_read": int(digitisation.get("pages_read") or 0), "lines_read": len(digitisation.get("document_lines") or []),
            "read_seconds": float(digitisation.get("read_seconds") or 0.0), "amount_claimed": claim.get("requested_amount"),
            "currency": claim.get("currency"), "message": MESSAGES.get(status, "")}


def _unread_claims(store: Repository) -> List[str]:
    """Claims with stored documents that the model has never classified and nothing has read yet."""
    read = {doc["claim_id"] for doc in store.list(collection="digitisations") if doc.get("claim_id")}
    portal = {doc["claim_id"] for doc in store.list(collection="portal_claims") if doc.get("claim_id")}
    pending: Dict[str, bool] = {}
    for doc in store.list(collection="documents"):
        claim_id = doc.get("claim_id")
        if not claim_id or claim_id in read or claim_id in portal:
            continue
        modelled = any(e.get("predicted_by") == "model" for e in doc.get("classification", []))
        pending[claim_id] = pending.get(claim_id, True) and not modelled
    return sorted(claim_id for claim_id, unread in pending.items() if unread)


async def auto_read_after_ingest(request: Request, call_next: Any) -> Any:
    """HTTP middleware: after a successful POST /ingest, the stored documents of the affected claims are read in the
    background (no button). Off when AUTO_READ_DOCUMENTS=0 or when documents are offline (cache-only replays)."""
    response = await call_next(request)
    if (request.method == "POST" and request.url.path.rstrip("/") == "/ingest" and response.status_code < 300
            and os.environ.get("AUTO_READ_DOCUMENTS", "1") != "0" and not get_settings().documents_offline):
        claim_ids = _unread_claims(store=get_store())
        if claim_ids:
            read_in_background(store=get_store(), claim_ids=claim_ids)
    return response
