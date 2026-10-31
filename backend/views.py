"""Read-side shaping: claim list rows, filters, claim detail and the dashboard aggregates."""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.finding import AmountKind, Finding, FindingStatus, Severity

from backend.graph import latest_run
from backend.master import load_product
from backend.store import Repository, now_iso

SEVERITY_RANK = {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3}
UNDECIDED = {FindingStatus.OPEN, FindingStatus.CLARIFICATION_REQUESTED}


def suspected_amount(finding: Finding) -> float:
    """A suspected finding's amount counts as 'suspected' only while no human has decided on it; once confirmed
    or corrected it moves into the deductions (effective_amount), dismissed it vanishes."""
    return finding.amount if finding.amount_kind == AmountKind.SUSPECTED and finding.status in UNDECIDED else 0.0


@dataclass
class ClaimFilters:
    type: Optional[str] = None
    provider: Optional[str] = None
    category: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    status: Optional[str] = None


def write_audit(store: Repository, actor: str, action: str, claim_id: Optional[str], details: Dict[str, Any]) -> Dict[str, Any]:
    row = {"audit_id": f"AUD-{uuid.uuid4().hex[:12]}", "ts": now_iso(), "actor": actor, "action": action,
           "claim_id": claim_id, "details": details}
    store.upsert(collection="audit", doc_id=row["audit_id"], doc=row)
    return row


def findings_by_claim(store: Repository) -> Dict[str, List[Finding]]:
    grouped: Dict[str, List[Finding]] = defaultdict(list)
    for doc in store.list(collection="findings"):
        grouped[doc["claim_id"]].append(Finding.model_validate(doc))
    return grouped


def leakage_totals(findings: List[Finding]) -> Tuple[float, float, Optional[str]]:
    """(calculated, suspected, max severity). Calculated = what the settlement deducts (reviewer corrections
    included, dismissed excluded); suspected = pattern amounts still waiting on a human."""
    calculated = 0.0
    suspected = 0.0
    top: Optional[Severity] = None
    for finding in findings:
        if finding.status == FindingStatus.DISMISSED:
            continue
        calculated += finding.effective_amount
        suspected += suspected_amount(finding=finding)
        if top is None or SEVERITY_RANK[finding.severity] > SEVERITY_RANK[top]:
            top = finding.severity
    return round(calculated, 2), round(suspected, 2), (top.value if top else None)


def initials(name: str) -> str:
    return "".join(part[0].upper() for part in name.split() if part)[:3] or "—"


def claim_summary(claim: Dict[str, Any], findings: List[Finding]) -> Dict[str, Any]:
    calculated, suspected, severity = leakage_totals(findings=findings)
    open_count = sum(1 for f in findings if f.status == FindingStatus.OPEN)
    return {"claim_id": claim["claim_id"], "claimant": initials(claim.get("claimant_name", "")),
            "claimant_id": claim.get("claimant_id"), "provider": claim.get("provider_name") or claim.get("provider_id"),
            "provider_id": claim.get("provider_id"), "claim_type": claim.get("claim_type"),
            "product_id": claim.get("product_id"), "incident_date": claim.get("incident_date"),
            "requested_amount": claim.get("requested_amount"), "currency": claim.get("currency"),
            "leakage_calculated": calculated, "leakage_suspected": suspected, "severity": severity,
            "findings": len(findings), "open_findings": open_count, "status": claim.get("status"),
            "updated_at": claim.get("updated_at") or claim.get("submitted_at")}


def _passes(claim: Dict[str, Any], findings: List[Finding], filters: ClaimFilters) -> bool:
    if filters.type and claim.get("claim_type") != filters.type.lower():
        return False
    if filters.provider and filters.provider not in (claim.get("provider_id"), claim.get("provider_name")):
        return False
    if filters.status and claim.get("status") != filters.status:
        return False
    amount = float(claim.get("requested_amount") or 0.0)
    if filters.min_amount is not None and amount < filters.min_amount:
        return False
    if filters.max_amount is not None and amount > filters.max_amount:
        return False
    incident = str(claim.get("incident_date") or "")
    if filters.from_date and incident < filters.from_date:
        return False
    if filters.to_date and incident > filters.to_date:
        return False
    if filters.category and not any(f.category.value == filters.category and f.status != FindingStatus.DISMISSED for f in findings):
        return False
    return True


def filtered_claims(store: Repository, filters: ClaimFilters) -> List[Tuple[Dict[str, Any], List[Finding]]]:
    grouped = findings_by_claim(store=store)
    rows = [(claim, grouped.get(claim["claim_id"], [])) for claim in store.list(collection="claims")]
    rows = [(claim, findings) for claim, findings in rows if _passes(claim=claim, findings=findings, filters=filters)]
    rows.sort(key=lambda pair: (str(pair[0].get("incident_date") or ""), pair[0]["claim_id"]), reverse=True)
    return rows


def claim_list(store: Repository, filters: ClaimFilters) -> List[Dict[str, Any]]:
    return [claim_summary(claim=claim, findings=findings) for claim, findings in filtered_claims(store=store, filters=filters)]


def document_view(doc: Dict[str, Any], known_types: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """`type` = the confirmed type, else what the master record knows (documents manifest), else None."""
    doc_type = doc.get("document_type") or (known_types or {}).get(doc["document_id"])
    return {"id": doc["document_id"], "name": doc.get("name"), "type": doc_type, "confirmed": bool(doc.get("document_type")),
            "pages": doc.get("pages", 1), "mime": doc.get("mime"), "uploaded_at": doc.get("uploaded_at")}


def classification_rows(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for doc in documents:
        for page in doc.get("classification", []):
            rows.append({"document_id": doc["document_id"], "document_name": doc.get("name"), "page_id": page["page_id"],
                         "page": page["page"], "predicted_type": page.get("predicted_type"),
                         "confidence": page.get("confidence"), "confirmed_type": page.get("confirmed_type"),
                         "predicted_by": page.get("predicted_by")})
    return rows


def claim_detail(store: Repository, claim_id: str) -> Optional[Dict[str, Any]]:
    claim = store.get(collection="claims", doc_id=claim_id)
    if claim is None:
        return None
    findings = [Finding.model_validate(doc) for doc in store.list(collection="findings", filter_={"claim_id": claim_id})]
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], f.finding_id))
    lines = store.list(collection="invoice_lines", filter_={"claim_id": claim_id})
    lines.sort(key=lambda line: (line.get("invoice_no", ""), int(line.get("serial_no") or 0)))
    documents = store.list(collection="documents", filter_={"claim_id": claim_id})
    documents.sort(key=lambda doc: doc.get("uploaded_at", ""))
    audit = store.list(collection="audit", filter_={"claim_id": claim_id})
    audit.sort(key=lambda row: row["ts"])
    product = load_product(store=store, product_id=claim["product_id"], currency=claim.get("currency", "INR"))
    master = store.get(collection="master_records", doc_id=claim_id) or {}
    known_types = master.get("document_types") or {}
    return {"claim": claim, "policy": store.get(collection="policies", doc_id=claim["policy_number"]),
            "product": product.model_dump(mode="json"), "lines": lines,
            "documents": [document_view(doc, known_types=known_types) for doc in documents], "classification": classification_rows(documents),
            "document_lines": master.get("document_lines", []), "document_facts": master.get("document_facts", {}),
            "findings": [f.model_dump(mode="json") for f in findings],
            "settlement": store.get(collection="settlements", doc_id=claim_id), "audit": audit,
            "run": latest_run(store=store, claim_id=claim_id), "summary": claim_summary(claim=claim, findings=findings),
            "reconciled": master.get("reconciled"), "printed_total": master.get("printed_total")}


# The dashboard adds claims from both markets, so amounts are reported in one currency. Rates are fixed for the
# demo and shown in the response; each claim page keeps its own currency.
REPORTING_CURRENCY = "INR"
FX_TO_REPORTING = {"INR": 1.0, "AED": 22.7}


def to_reporting(amount: float, currency: Optional[str]) -> float:
    return amount * FX_TO_REPORTING.get((currency or REPORTING_CURRENCY).upper(), 1.0)


def dashboard(store: Repository, filters: ClaimFilters) -> Dict[str, Any]:
    rows = filtered_claims(store=store, filters=filters)
    settled_ids = {doc["claim_id"] for doc in store.list(collection="settlements")}
    run_ids = {doc["claim_id"] for doc in store.list(collection="runs")}
    by_category: Dict[str, Dict[str, Any]] = {}
    by_severity: Dict[str, Dict[str, Any]] = {}
    by_provider: Dict[str, Dict[str, Any]] = {}
    by_check: Dict[str, Dict[str, Any]] = {}
    total_calculated = total_suspected = 0.0
    flagged = awaiting = 0
    for claim, findings in rows:
        calculated, suspected, _ = leakage_totals(findings=findings)
        fx = to_reporting(1.0, claim.get("currency"))
        calculated, suspected = calculated * fx, suspected * fx
        total_calculated += calculated
        total_suspected += suspected
        live = [f for f in findings if f.status != FindingStatus.DISMISSED]
        if live:
            flagged += 1
        if any(f.status == FindingStatus.OPEN for f in findings):
            awaiting += 1
        provider_key = claim.get("provider_id") or "unknown"
        provider = by_provider.setdefault(provider_key, {"provider_id": provider_key, "provider_name": claim.get("provider_name") or provider_key,
                                                         "claims": 0, "flagged": 0, "leakage_calculated": 0.0, "leakage_suspected": 0.0})
        provider["claims"] += 1
        provider["flagged"] += 1 if live else 0
        provider["leakage_calculated"] = round(provider["leakage_calculated"] + calculated, 2)
        provider["leakage_suspected"] = round(provider["leakage_suspected"] + suspected, 2)
        for finding in live:
            cal = finding.effective_amount * fx
            sus = suspected_amount(finding=finding) * fx
            for bucket, key in ((by_category, finding.category.value), (by_check, finding.check_id.value)):
                entry = bucket.setdefault(key, {"key": key, "count": 0, "amount_calculated": 0.0, "amount_suspected": 0.0})
                entry["count"] += 1
                entry["amount_calculated"] = round(entry["amount_calculated"] + cal, 2)
                entry["amount_suspected"] = round(entry["amount_suspected"] + sus, 2)
            sev = by_severity.setdefault(finding.severity.value, {"severity": finding.severity.value, "count": 0, "amount": 0.0})
            sev["count"] += 1
            sev["amount"] = round(sev["amount"] + cal + sus, 2)
    categories = [{"category": v["key"], **{k: v[k] for k in ("count", "amount_calculated", "amount_suspected")}} for v in by_category.values()]
    checks = [{"check_id": v["key"], **{k: v[k] for k in ("count", "amount_calculated", "amount_suspected")}} for v in by_check.values()]
    providers = sorted(by_provider.values(), key=lambda p: p["leakage_calculated"] + p["leakage_suspected"], reverse=True)
    severities = sorted(by_severity.values(), key=lambda s: SEVERITY_RANK[Severity(s["severity"])], reverse=True)
    return {"claims": len(rows), "processed": sum(1 for claim, _ in rows if claim["claim_id"] in settled_ids or claim["claim_id"] in run_ids),
            "flagged": flagged, "leakage_calculated": round(total_calculated, 2), "leakage_suspected": round(total_suspected, 2),
            "awaiting_review": awaiting, "reporting_currency": REPORTING_CURRENCY,
            "fx_rates": {k: v for k, v in FX_TO_REPORTING.items() if k != REPORTING_CURRENCY},
            "by_category": sorted(categories, key=lambda c: c["count"], reverse=True),
            "by_severity": severities, "by_provider": providers, "by_check": sorted(checks, key=lambda c: c["count"], reverse=True)}
