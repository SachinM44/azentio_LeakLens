"""POST /ingest: structured files (CSV / XLSX / JSON) and documents (PDF / JPG / PNG) into the master dataset.

Every row is validated against the Pydantic models in core.schemas.master plus a few basic rules. Rows with
errors are reported row by row and NOT stored; rows with warnings are stored and reported with accepted=true.
Nothing is dropped silently. Documents are stored and attached to the claim whose id prefixes the file name.
"""
from __future__ import annotations

import io
import json
import logging
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from core.schemas.finding import ValidationIssue
from core.schemas.master import Claim, HistoryRecord, InvoiceLine, Policy, ProductConfig

from backend.master import manifest_for_claim, refresh_master_records
from backend.settings import get_settings
from backend.store import Repository, now_iso

logger = logging.getLogger(__name__)

TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls", ".json"}
DOCUMENT_MIMES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

ENTITY_ALIASES = {"claims": "claims", "claim": "claims", "invoice_lines": "invoice_lines", "lines": "invoice_lines",
                  "invoice_line": "invoice_lines", "policies": "policies", "policy": "policies",
                  "history": "history", "histories": "history", "claim_history": "history", "settlements": "history",
                  "providers": "providers", "provider": "providers", "claimants": "claimants", "claimant": "claimants",
                  "members": "claimants", "products": "products", "product": "products", "configs": "products",
                  "product_configs": "products"}

ENTITY_MODELS: Dict[str, type] = {"claims": Claim, "invoice_lines": InvoiceLine, "policies": Policy,
                                  "history": HistoryRecord, "products": ProductConfig}
ENTITY_ID_FIELD = {"claims": "claim_id", "invoice_lines": "line_id", "policies": "policy_number", "history": "claim_id",
                   "providers": "provider_id", "claimants": "claimant_id", "products": "product_id"}

LIST_FIELDS = {"members", "invoice_numbers", "non_payable_items", "network_provider_ids", "declared_ped", "keywords",
               "codes", "repeatable_service_codes", "sublimits", "exclusions", "lines"}
DICT_FIELDS = {"deductible", "copay", "required_documents", "extra"}
DATE_FIELDS = {"incident_date", "admission_date", "discharge_date", "service_date", "start_date", "end_date", "paid_on",
               "submitted_at"}
NESTED_PREFIXES = ("deductible", "copay")
CLAIM_FIELDS = set(Claim.model_fields)

FILENAME_TYPE_HINTS: List[Tuple[str, str]] = [
    ("discharge", "discharge_summary"), ("pharmacy", "medicine_pharmacy_bills"), ("medicine", "medicine_pharmacy_bills"),
    ("interim", "interim_running_bill"), ("bill", "itemized_final_hospital_bill"), ("invoice", "itemized_final_hospital_bill"),
    ("claim_form", "claim_form"), ("claimform", "claim_form"), ("form", "claim_form"), ("prescription", "prescriptions"),
    ("report", "diagnostic_reports"), ("lab", "diagnostic_reports"), ("kyc", "kyc_document"), ("preauth", "pre_auth_form"),
    ("pre_auth", "pre_auth_form"), ("policy", "policy_schedule"), ("cheque", "cancelled_cheque_neft"), ("fir", "mlc_fir_report"),
]


class IngestResult(BaseModel):
    batch_id: str = Field(..., description="Id of this upload batch")
    counts: Dict[str, int] = Field(default_factory=dict, description="Accepted rows per entity (+ documents)")
    claims_created: int = Field(default=0, description="Claims that did not exist before this batch")
    claims_affected: List[str] = Field(default_factory=list, description="Claims whose master record was rebuilt")
    documents: List[Dict[str, Any]] = Field(default_factory=list, description="Stored documents: id, name, claim_id, pages")
    validation: List[ValidationIssue] = Field(default_factory=list, description="Row-level report; nothing dropped silently")


# ----------------------------------------------------------------------------------------------- file parsing


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(key).strip().lower()).strip("_")


def _frame_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    frame = frame.rename(columns=_normalise_key)
    frame = frame.loc[:, [col for col in frame.columns if col and not col.startswith("unnamed")]]
    rows: List[Dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row = {key: (None if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""
                     else (value.strip() if isinstance(value, str) else value)) for key, value in raw.items()}
        rows.append(row)
    return rows


def detect_entity(columns: List[str]) -> Optional[str]:
    """Which table a file holds, from its column names alone."""
    cols = set(columns)
    if "line_id" in cols or {"invoice_no", "description", "amount"} <= cols:
        return "invoice_lines"
    if "paid_amount" in cols or "approved_amount" in cols:
        return "history"
    if "annual_limit" in cols or "holder_id" in cols:
        return "policies"
    if "auto_triage_threshold" in cols or ({"product_id", "insurer"} <= cols):
        return "products"
    if "claim_id" in cols and ("requested_amount" in cols or {"claimant_id", "provider_id"} <= cols):
        return "claims"
    if "provider_id" in cols and "claim_id" not in cols:
        return "providers"
    if "claimant_id" in cols and "claim_id" not in cols:
        return "claimants"
    return None


def parse_tabular(name: str, data: bytes) -> Tuple[Dict[str, List[Dict[str, Any]]], List[ValidationIssue]]:
    """A file -> {entity: rows}; undetected tables are reported, not dropped."""
    suffix = Path(name).suffix.lower()
    tables: Dict[str, List[Dict[str, Any]]] = {}
    issues: List[ValidationIssue] = []
    candidates: List[Tuple[Optional[str], List[Dict[str, Any]]]] = []  # (hint, rows)
    try:
        if suffix == ".csv":
            candidates.append((None, _frame_rows(pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False))))
        elif suffix in {".xlsx", ".xls"}:
            for sheet, frame in pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str).items():
                candidates.append((ENTITY_ALIASES.get(_normalise_key(sheet)), _frame_rows(frame)))
        elif suffix == ".json":
            payload = json.loads(data.decode("utf-8-sig"))
            if isinstance(payload, dict):
                for key, value in payload.items():
                    entity = ENTITY_ALIASES.get(_normalise_key(key))
                    if isinstance(value, list) and entity:
                        candidates.append((entity, [{_normalise_key(k): v for k, v in row.items()} for row in value]))
                    elif isinstance(value, list):
                        issues.append(ValidationIssue(file=name, field=str(key), problem=f"unknown entity '{key}' ignored"))
                if not candidates and "claim_id" in {_normalise_key(k) for k in payload}:
                    candidates.append(("claims", [{_normalise_key(k): v for k, v in payload.items()}]))
            elif isinstance(payload, list):
                candidates.append((None, [{_normalise_key(k): v for k, v in row.items()} for row in payload if isinstance(row, dict)]))
    except Exception as exc:
        issues.append(ValidationIssue(file=name, problem=f"file could not be parsed: {exc}"))
        return tables, issues
    for hint, rows in candidates:
        if not rows:
            issues.append(ValidationIssue(file=name, problem="file or sheet has no rows"))
            continue
        entity = hint or detect_entity(columns=list(rows[0].keys()))
        if entity is None:
            issues.append(ValidationIssue(file=name, problem=f"could not tell which table this is from columns {sorted(rows[0].keys())[:8]}"))
            continue
        tables.setdefault(entity, []).extend(rows)
    return tables, issues


# ----------------------------------------------------------------------------------------------- row coercion


def _parse_listish(value: Any) -> Any:
    if value is None or isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in re.split(r"[;|]", text) if part.strip()]


def _parse_dictish(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        return value
    text = str(value).strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _parse_date(value: Any) -> Any:
    if value is None or isinstance(value, (date, datetime)):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", text):
        return text
    try:
        parsed = pd.to_datetime(text, dayfirst=False)
    except Exception:
        return value
    return parsed.date().isoformat() if parsed.hour == 0 and parsed.minute == 0 else parsed.isoformat()


def coerce_row(entity: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """Flat CSV columns into the nested model shape; lists and dicts from JSON strings; dates normalised."""
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            continue
        nested = next((p for p in NESTED_PREFIXES if key.startswith(p + "_") or key.startswith(p + ".")), None)
        if nested and entity == "policies":
            out.setdefault(nested, {})[key[len(nested) + 1:]] = value
            continue
        if key in LIST_FIELDS:
            value = _parse_listish(value)
        elif key in DICT_FIELDS:
            value = _parse_dictish(value)
        elif key in DATE_FIELDS:
            value = _parse_date(value)
        elif key in {"claim_type", "category", "code_system"} and isinstance(value, str):
            value = value.strip().lower()
        out[key] = value
    if entity == "claims":
        extra = {key: str(out.pop(key)) for key in list(out) if key not in CLAIM_FIELDS}
        if extra:
            out["extra"] = {**extra, **(out.get("extra") or {})}
    if entity == "invoice_lines" and not out.get("line_id") and out.get("claim_id") and out.get("invoice_no") and out.get("serial_no"):
        out["line_id"] = f"{out['claim_id']}:{out['invoice_no']}:{out['serial_no']}"
    return out


# ----------------------------------------------------------------------------------------------- validation


def _rules(entity: str, model: Any, known: Dict[str, Set[str]]) -> List[Tuple[str, str, bool]]:
    """Basic rules beyond the schema: (field, problem, is_error)."""
    found: List[Tuple[str, str, bool]] = []
    if entity == "claims":
        if model.admission_date and model.discharge_date and model.discharge_date < model.admission_date:
            found.append(("discharge_date", f"discharge {model.discharge_date} is before admission {model.admission_date}", True))
        if model.proposed_settlement is not None and model.proposed_settlement < 0:
            found.append(("proposed_settlement", "proposed settlement is negative", True))
        if known["policies"] and model.policy_number not in known["policies"]:
            found.append(("policy_number", f"policy {model.policy_number} is not loaded; claim kept, policy checks will ask for it", False))
    elif entity == "invoice_lines":
        if model.quantity < 0:
            found.append(("quantity", "quantity is negative", True))
        if model.unit_price is not None and model.unit_price < 0:
            found.append(("unit_price", "negative unit price kept (return / discount)", False))
        if model.amount < 0:
            found.append(("amount", "negative line amount kept (return / discount)", False))
        if known["claims"] and model.claim_id not in known["claims"]:
            found.append(("claim_id", f"claim {model.claim_id} is not loaded; line kept unattached", False))
    elif entity == "policies":
        if model.end_date < model.start_date:
            found.append(("end_date", f"cover end {model.end_date} is before start {model.start_date}", True))
        if model.annual_limit < 0:
            found.append(("annual_limit", "annual limit is negative", True))
    elif entity == "history":
        for field in ("requested_amount", "approved_amount", "paid_amount"):
            if getattr(model, field) < 0:
                found.append((field, f"{field} is negative", True))
        if model.paid_on and model.paid_on < model.incident_date:
            found.append(("paid_on", f"paid {model.paid_on} before the incident {model.incident_date}", False))
    return found


def validate_rows(entity: str, rows: List[Dict[str, Any]], file_name: str, row_offset: int,
                  known: Dict[str, Set[str]]) -> Tuple[List[Dict[str, Any]], List[ValidationIssue]]:
    """Returns (accepted docs, issues). An accepted doc is the model dumped JSON-safe (or the raw row for
    providers / claimants, which have no model)."""
    accepted: List[Dict[str, Any]] = []
    issues: List[ValidationIssue] = []
    id_field = ENTITY_ID_FIELD[entity]
    seen_ids: Set[str] = set()
    model_cls = ENTITY_MODELS.get(entity)
    for index, raw in enumerate(rows):
        row_no = index + row_offset
        row = coerce_row(entity=entity, row=raw)
        row_id = row.get(id_field)
        if row_id is None or str(row_id).strip() == "":
            issues.append(ValidationIssue(file=file_name, row=row_no, field=id_field, problem=f"{id_field} is missing"))
            continue
        row_id = str(row_id).strip()
        if row_id in seen_ids:
            issues.append(ValidationIssue(file=file_name, row=row_no, field=id_field, problem=f"duplicate {id_field} '{row_id}' in this file"))
            continue
        if model_cls is None:
            seen_ids.add(row_id)
            accepted.append({**row, id_field: row_id})
            continue
        try:
            model = model_cls.model_validate(row)
        except ValidationError as exc:
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"]) or id_field
                issues.append(ValidationIssue(file=file_name, row=row_no, field=field, problem=error["msg"]))
            continue
        rule_hits = _rules(entity=entity, model=model, known=known)
        errors = [hit for hit in rule_hits if hit[2]]
        for field, problem, is_error in rule_hits:
            issues.append(ValidationIssue(file=file_name, row=row_no, field=field, problem=problem, accepted=not errors))
        if errors:
            continue
        seen_ids.add(row_id)
        known[entity].add(row_id)
        accepted.append(model.model_dump(mode="json"))
    return accepted, issues


# ----------------------------------------------------------------------------------------------- documents


def _pdf_pages(data: bytes) -> int:
    try:
        import pymupdf  # PyMuPDF
    except ImportError:  # the older import name
        import fitz as pymupdf  # type: ignore
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return pdf.page_count


def match_claim_id(file_name: str, claim_ids: Set[str]) -> Optional[str]:
    """The longest known claim id that prefixes the file name, e.g. CLM-2026-0007_bill.pdf -> CLM-2026-0007."""
    stem = Path(file_name).name
    best = ""
    for claim_id in claim_ids:
        if stem.startswith(claim_id) and (len(stem) == len(claim_id) or stem[len(claim_id)] in "_-. "):
            if len(claim_id) > len(best):
                best = claim_id
    return best or None


def guess_document_type(file_name: str) -> Tuple[str, float]:
    lowered = file_name.lower()
    for keyword, document_type in FILENAME_TYPE_HINTS:
        if keyword in lowered:
            return document_type, 0.6
    return "other_documents", 0.3


def store_document(store: Repository, name: str, data: bytes, claim_ids: Set[str]) -> Tuple[Dict[str, Any], List[ValidationIssue]]:
    suffix = Path(name).suffix.lower()
    mime = DOCUMENT_MIMES[suffix]
    issues: List[ValidationIssue] = []
    pages = 1
    if suffix == ".pdf":
        try:
            pages = _pdf_pages(data=data)
        except Exception as exc:
            issues.append(ValidationIssue(file=name, problem=f"page count unavailable ({exc}); stored as 1 page", accepted=True))
    document_id = store.save_document(data=data, name=name, mime=mime)
    claim_id = match_claim_id(file_name=name, claim_ids=claim_ids)
    predicted_type, confidence = guess_document_type(file_name=name)
    classification = [{"page_id": f"{document_id}:{page}", "page": page, "predicted_type": predicted_type,
                       "confidence": confidence, "confirmed_type": None, "predicted_by": "filename"}
                      for page in range(1, pages + 1)]
    meta = {**store.get(collection="documents", doc_id=document_id), "claim_id": claim_id, "pages": pages,
            "document_type": None, "classification": classification}
    store.upsert(collection="documents", doc_id=document_id, doc=meta)
    if claim_id is None:
        issues.append(ValidationIssue(file=name, problem="document stored but not attached: file name does not start with a known claim id", accepted=True))
    return meta, issues


def import_manifest_documents(store: Repository, claim_ids: List[str]) -> List[Dict[str, Any]]:
    """Rendered files the synthetic documents manifest lists for these claims become stored documents attached
    to the claim (skipped when a file of that name is already on the claim). Returns the stored documents."""
    imported: List[Dict[str, Any]] = []
    for claim_id in claim_ids:
        entry = manifest_for_claim(claim_id=claim_id)
        if entry is None:
            continue
        present = {doc.get("name") for doc in store.list(collection="documents", filter_={"claim_id": claim_id})}
        for doc in entry.documents:
            if doc.path is None or doc.name in present or doc.path.suffix.lower() not in DOCUMENT_MIMES:
                continue
            if not doc.path.exists():
                logger.warning("manifest file missing", extra={"claim_id": claim_id, "path": str(doc.path)})
                continue
            meta, _ = store_document(store=store, name=doc.name, data=doc.path.read_bytes(), claim_ids={claim_id})
            meta["claim_id"] = claim_id  # the manifest binds the file to the claim even without the id prefix
            meta["manifest_document_id"] = doc.document_id
            store.upsert(collection="documents", doc_id=meta["document_id"], doc=meta)
            imported.append({key: meta.get(key) for key in ("document_id", "name", "claim_id", "pages", "mime")})
            present.add(doc.name)
    return imported


# ----------------------------------------------------------------------------------------------- orchestration


def _known_ids(store: Repository) -> Dict[str, Set[str]]:
    known = {entity: set() for entity in ENTITY_ID_FIELD}
    for entity, id_field in ENTITY_ID_FIELD.items():
        known[entity] = {str(doc[id_field]) for doc in store.list(collection=entity) if doc.get(id_field) is not None}
    return known


def ingest_files(store: Repository, files: List[Tuple[str, bytes]], actor: str) -> IngestResult:
    """The whole /ingest flow for one batch of uploaded files."""
    batch_id = f"BATCH-{uuid.uuid4().hex[:10]}"
    result = IngestResult(batch_id=batch_id)
    known = _known_ids(store=store)
    existing_claims = set(known["claims"])
    affected: Set[str] = set()
    refresh_all = False
    for name, data in files:
        suffix = Path(name).suffix.lower()
        if suffix in DOCUMENT_MIMES:
            continue  # documents after the tables, so a claim uploaded in the same batch can receive its file
        if suffix not in TABULAR_SUFFIXES:
            result.validation.append(ValidationIssue(file=name, problem=f"unsupported file type '{suffix}'"))
            continue
        tables, issues = parse_tabular(name=name, data=data)
        result.validation.extend(issues)
        row_offset = 1 if suffix == ".json" else 2  # header line counts in CSV / XLSX
        for entity, rows in tables.items():
            accepted, issues = validate_rows(entity=entity, rows=rows, file_name=name, row_offset=row_offset, known=known)
            result.validation.extend(issues)
            id_field = ENTITY_ID_FIELD[entity]
            stamp = now_iso()
            for doc in accepted:
                if entity == "claims":
                    doc["updated_at"] = stamp
                if entity in ("claims", "invoice_lines"):
                    affected.add(doc["claim_id"])
                else:
                    refresh_all = True
            store.bulk_upsert(collection=entity, docs={str(doc[id_field]): doc for doc in accepted})
            result.counts[entity] = result.counts.get(entity, 0) + len(accepted)
            logger.info("ingested table", extra={"batch_id": batch_id, "file": name, "entity": entity,
                                                 "accepted": len(accepted), "rows": len(rows)})
    for name, data in files:
        if Path(name).suffix.lower() not in DOCUMENT_MIMES:
            continue
        meta, issues = store_document(store=store, name=name, data=data, claim_ids=known["claims"])
        result.validation.extend(issues)
        result.documents.append({key: meta.get(key) for key in ("document_id", "name", "claim_id", "pages", "mime")})
        result.counts["documents"] = result.counts.get("documents", 0) + 1
        if meta.get("claim_id"):
            affected.add(meta["claim_id"])
    result.claims_created = len(known["claims"] - existing_claims)
    imported = (import_manifest_documents(store=store, claim_ids=sorted(known["claims"] - existing_claims))
                if get_settings().import_dataset_documents else [])
    if imported:
        result.documents.extend(imported)
        result.counts["documents"] = result.counts.get("documents", 0) + len(imported)
        affected.update(doc["claim_id"] for doc in imported)
    targets = sorted(known["claims"]) if refresh_all else sorted(affected & known["claims"])
    refresh_master_records(store=store, claim_ids=targets)
    result.claims_affected = targets
    store.upsert(collection="batches", doc_id=batch_id,
                 doc={"batch_id": batch_id, "ts": now_iso(), "actor": actor, "files": [name for name, _ in files],
                      "counts": result.counts, "claims_created": result.claims_created,
                      "issues": len(result.validation), "rejected_rows": sum(1 for i in result.validation if not i.accepted)})
    return result
