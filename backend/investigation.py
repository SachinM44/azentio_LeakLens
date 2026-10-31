"""Investigator workspace data: policy terms, notes, related claims and the document-vs-claim comparison."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.master import ProductConfig

from backend.store import Repository

STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}
MAX_RELATED = 20


# ----------------------------------------------------------------------------------------------- policy terms / notes


def _money(amount: Any, currency: str) -> str:
    return f"{currency} {float(amount):,.2f}"


def policy_terms(policy: Optional[Dict[str, Any]], product: ProductConfig) -> List[Dict[str, Any]]:
    """The policy terms an investigator needs beside the findings, as {term, value, clause_id?} rows."""
    if not policy:
        return []
    cur = policy.get("currency") or product.currency
    copay = policy.get("copay") or {}
    deductible = policy.get("deductible") or {}
    terms: List[Dict[str, Any]] = [
        {"term": "Annual limit", "value": _money(policy.get("annual_limit") or 0, cur)},
        {"term": "Room rent per day", "value": _money(policy["room_rent_limit_per_day"], cur) if policy.get("room_rent_limit_per_day") else "No limit"},
        {"term": "ICU per day", "value": _money(policy["icu_limit_per_day"], cur) if policy.get("icu_limit_per_day") else "No limit"},
        {"term": "Copay inpatient", "value": f"{copay.get('inpatient_pct', 0):g}%"},
        {"term": "Copay outpatient", "value": f"{copay.get('outpatient_pct', 0):g}%"},
        {"term": "Copay pharmacy", "value": f"{copay.get('pharmacy_pct', 0):g}%"},
        {"term": "Deductible", "value": f"{_money(deductible.get('amount', 0), cur)} "
                                         f"({str(deductible.get('basis', 'per_claim')).replace('_', ' ')})"},
    ]
    for sub in policy.get("sublimits") or []:
        terms.append({"term": f"Sub-limit: {sub.get('name')}",
                      "value": f"{_money(sub.get('limit', 0), cur)} {str(sub.get('basis', '')).replace('_', ' ')}".strip(),
                      "clause_id": sub.get("clause_id")})
    for exclusion in policy.get("exclusions") or []:
        terms.append({"term": f"Exclusion: {exclusion.get('exclusion_id')}", "value": exclusion.get("text", ""),
                      "clause_id": exclusion.get("clause_id")})
    terms.append({"term": "Waiting period", "value": f"{policy.get('waiting_period_days', 0)} days"})
    terms.append({"term": "Pre-existing disease waiting period", "value": f"{policy.get('ped_waiting_days', 0)} days"})
    network = policy.get("network_provider_ids") or []
    terms.append({"term": "Network", "value": f"{len(network)} providers" if network else "Any provider"})
    non_payable = set(policy.get("non_payable_items") or []) | set(product.non_payable_items)
    terms.append({"term": "Non-payable items", "value": f"{len(non_payable)} items"})
    return terms


def claim_notes(store: Repository, claim_id: str) -> List[Dict[str, Any]]:
    notes = store.list(collection="notes", filter_={"claim_id": claim_id})
    notes.sort(key=lambda note: note["ts"], reverse=True)
    return notes


# ----------------------------------------------------------------------------------------------- related claims


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _mask(value: Any) -> str:
    raw = re.sub(r"\s", "", str(value or ""))
    return f"****{raw[-4:]}" if raw else ""


def _as_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _matches(claim: Dict[str, Any], other: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    same_member = bool(claim.get("claimant_id")) and claim.get("claimant_id") == other.get("claimant_id")
    shared_invoices = sorted(set(claim.get("invoice_numbers") or []) & set(other.get("invoice_numbers") or []))
    for invoice in shared_invoices:
        out.append({"attribute": "invoice_number", "label": "Same invoice number", "value": invoice, "strength": "strong"})
    if not same_member:
        if _digits(claim.get("bank_account")) and _digits(claim.get("bank_account")) == _digits(other.get("bank_account")):
            out.append({"attribute": "bank_account", "label": "Same bank account, different member",
                        "value": _mask(claim["bank_account"]), "strength": "strong"})
        if _digits(claim.get("contact_phone")) and _digits(claim.get("contact_phone")) == _digits(other.get("contact_phone")):
            out.append({"attribute": "phone", "label": "Same phone, different member",
                        "value": _mask(claim["contact_phone"]), "strength": "strong"})
        if _norm(claim.get("address")) and _norm(claim.get("address")) == _norm(other.get("address")):
            out.append({"attribute": "address", "label": "Same address, different member", "value": claim["address"],
                        "strength": "medium"})
    else:
        mine, theirs = _as_date(claim.get("incident_date")), _as_date(other.get("incident_date"))
        if (claim.get("provider_id") and claim.get("provider_id") == other.get("provider_id") and mine and theirs
                and abs((mine - theirs).days) <= 30):
            out.append({"attribute": "same_member_same_provider_30d", "label": "Same member, same provider within 30 days",
                        "value": f"{other.get('provider_id')} on {theirs.isoformat()}", "strength": "medium"})
        out.append({"attribute": "same_member", "label": "Same member", "value": claim["claimant_id"], "strength": "weak"})
    return out


def related_claims(store: Repository, claim: Dict[str, Any], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Other claims (current and history) linked to this one, strongest link first, at most 20."""
    claim_id = claim["claim_id"]
    candidates: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for doc in store.list(collection="history"):
        candidates[doc["claim_id"]] = ("history", doc)
    for doc in store.list(collection="claims"):
        candidates[doc["claim_id"]] = ("claim", doc)  # a current claim wins over a history row with the same id
    candidates.pop(claim_id, None)
    rows: List[Dict[str, Any]] = []
    for other_id, (source, other) in candidates.items():
        matches = _matches(claim=claim, other=other)
        if not matches:
            continue
        strength = max((m.pop("strength") for m in matches), key=lambda s: STRENGTH_RANK[s])
        rows.append({"claim_id": other_id, "source": source, "claimant_id": other.get("claimant_id"),
                     "claimant_name": other.get("claimant_name"), "provider_id": other.get("provider_id"),
                     "provider_name": other.get("provider_name"), "policy_number": other.get("policy_number"),
                     "incident_date": other.get("incident_date"), "requested_amount": other.get("requested_amount"),
                     "currency": other.get("currency") or claim.get("currency"),
                     "status": other.get("status") or ("paid" if source == "history" else None),
                     "strength": strength, "matches": matches,
                     "finding_ids": [f["finding_id"] for f in findings if other_id in (f.get("related_claim_ids") or [])]})
    rows.sort(key=lambda row: (-STRENGTH_RANK[row["strength"]], str(row.get("incident_date") or "")), reverse=False)
    return rows[:MAX_RELATED]


# ----------------------------------------------------------------------------------------------- document comparison

FIELDS = [("claimant_name", "Claimant name"), ("policy_number", "Policy number"), ("provider_name", "Provider"),
          ("admission_date", "Admission date"), ("discharge_date", "Discharge date"), ("invoice_no", "Invoice number"),
          ("total_amount", "Total amount")]


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _field_status(field: str, claim_value: Any, document_value: Any, claim: Dict[str, Any]) -> str:
    if claim_value in (None, "") and document_value in (None, ""):
        return "not_read"
    if document_value in (None, ""):
        return "only_in_claim"
    if claim_value in (None, ""):
        return "only_in_document"
    if field == "total_amount":
        a, b = _to_float(claim_value), _to_float(document_value)
        return "match" if a is not None and b is not None and abs(a - b) <= 1.0 else "mismatch"
    if field == "invoice_no":
        known = {_norm(n) for n in claim.get("invoice_numbers") or []}
        return "match" if _norm(document_value) in known else "mismatch"
    if field.endswith("_date"):
        return "match" if str(claim_value)[:10] == str(document_value)[:10] else "mismatch"
    return "match" if _norm(claim_value) == _norm(document_value) else "mismatch"


def _same_line(claim_line: Dict[str, Any], doc_line: Dict[str, Any]) -> bool:
    if claim_line.get("code") and doc_line.get("code"):
        return _norm(claim_line["code"]) == _norm(doc_line["code"])
    return _norm(claim_line.get("description")) == _norm(doc_line.get("description"))


def comparison(store: Repository, claim: Dict[str, Any]) -> Dict[str, Any]:
    """The claim as submitted against what the documents say (DOC's `digitisations` row). Without an extraction
    the fields are `not_read`, except those the dataset's documents manifest already states."""
    claim_id = claim["claim_id"]
    digitised = store.get(collection="digitisations", doc_id=claim_id) or {}
    master = store.get(collection="master_records", doc_id=claim_id) or {}
    documents = store.list(collection="documents", filter_={"claim_id": claim_id})
    names = {doc["document_id"]: doc.get("name") for doc in documents}
    lines = store.list(collection="invoice_lines", filter_={"claim_id": claim_id})
    lines.sort(key=lambda line: (line.get("invoice_no", ""), int(line.get("serial_no") or 0)))
    claim_total = round(sum(float(line.get("amount") or 0) for line in lines), 2) if lines else claim.get("requested_amount")
    facts = dict(digitised.get("document_facts") or {}) if digitised else dict(master.get("document_facts") or {})
    fact_sources = digitised.get("document_fact_sources") or {}
    printed_total = digitised.get("printed_total") if digitised else master.get("printed_total")
    claim_values = {"claimant_name": claim.get("claimant_name"), "policy_number": claim.get("policy_number"),
                    "provider_name": claim.get("provider_name"), "admission_date": claim.get("admission_date"),
                    "discharge_date": claim.get("discharge_date"),
                    "invoice_no": ", ".join(claim.get("invoice_numbers") or []) or None, "total_amount": claim_total}
    fields: List[Dict[str, Any]] = []
    for field, label in FIELDS:
        document_value = facts.get(field)
        if field == "total_amount":
            document_value = printed_total if printed_total is not None else (facts.get("net_payable") or facts.get("total"))
        status = _field_status(field=field, claim_value=claim_values[field], document_value=document_value, claim=claim)
        if document_value in (None, "") and not digitised:
            status = "not_read"
        fields.append({"field": field, "label": label, "claim_value": claim_values[field], "document_value": document_value,
                       "status": status, "source": fact_sources.get(field)})

    def source_of(doc_line: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not doc_line.get("document_id"):
            return None
        return {"document_id": doc_line["document_id"], "document_name": names.get(doc_line["document_id"]),
                "page": doc_line.get("page")}

    document_lines = list(digitised.get("document_lines") or [])
    unmatched = list(lines)
    rows: List[Dict[str, Any]] = []
    for doc_line in document_lines:
        partner = next((line for line in unmatched if _same_line(claim_line=line, doc_line=doc_line)), None)
        doc_amount = round(float(doc_line.get("amount") or 0), 2)
        if partner is None:
            rows.append({"status": "only_in_document", "description": doc_line.get("description"), "code": doc_line.get("code"),
                         "claim_amount": None, "document_amount": doc_amount, "difference": None, "claim_line_id": None,
                         "source": source_of(doc_line)})
            continue
        unmatched.remove(partner)
        claim_amount = round(float(partner.get("amount") or 0), 2)
        difference = round(claim_amount - doc_amount, 2)
        rows.append({"status": "match" if abs(difference) <= 1.0 else "amount_differs", "description": partner.get("description"),
                     "code": partner.get("code") or doc_line.get("code"), "claim_amount": claim_amount,
                     "document_amount": doc_amount, "difference": difference, "claim_line_id": partner.get("line_id"),
                     "source": source_of(doc_line)})
    if document_lines:  # without document lines there is nothing to say a claim line is missing from
        for line in unmatched:
            rows.append({"status": "only_in_claim", "description": line.get("description"), "code": line.get("code"),
                         "claim_amount": round(float(line.get("amount") or 0), 2), "document_amount": None, "difference": None,
                         "claim_line_id": line.get("line_id"), "source": None})
    document_total = printed_total if printed_total is not None else (
        round(sum(float(line.get("amount") or 0) for line in document_lines), 2) if document_lines else None)
    count = lambda status: sum(1 for row in rows if row["status"] == status)  # noqa: E731
    summary = {"fields_checked": sum(1 for f in fields if f["status"] in ("match", "mismatch")),
               "fields_mismatched": sum(1 for f in fields if f["status"] == "mismatch"),
               "lines_matched": count("match"), "lines_only_in_document": count("only_in_document"),
               "lines_only_in_claim": count("only_in_claim"), "lines_amount_differs": count("amount_differs"),
               "claim_total": claim_total, "document_total": document_total,
               "total_difference": None if document_total is None or claim_total is None else round(float(claim_total) - float(document_total), 2)}
    return {"claim_id": claim_id, "extracted": bool(digitised), "extracted_by": digitised.get("extracted_by"),
            "extracted_at": digitised.get("extracted_at"), "model": digitised.get("model"),
            "read_seconds": digitised.get("read_seconds"),
            "documents": [{"document_id": doc["document_id"], "name": doc.get("name"), "type": doc.get("document_type"),
                           "pages": doc.get("pages", 1)} for doc in documents],
            "fields": fields, "lines": rows, "summary": summary}
