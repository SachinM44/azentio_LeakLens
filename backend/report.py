"""The investigation report for one claim: one JSON document, or the same content as a printable HTML page."""
from __future__ import annotations

import html
from typing import Any, Dict, List

from backend.investigation import comparison, related_claims
from backend.store import Repository, now_iso


def build_report(store: Repository, detail: Dict[str, Any], generated_by: str) -> Dict[str, Any]:
    claim = detail["claim"]
    settlement = detail.get("settlement") or {}
    findings = detail.get("findings", [])
    keep = ("finding_id", "check_id", "category", "severity", "amount", "amount_kind", "currency", "status", "rule_id",
            "rule_text", "calculation", "reason", "line_ids", "clause", "related_claim_ids", "correction", "original",
            "decision_history", "decision_reason", "decided_by", "decided_at", "escalated_to", "corrected_amount",
            "reviewer_note", "recommendation", "recommendation_confidence", "recommendation_note")
    return {"generated_at": now_iso(), "generated_by": generated_by, "claim": claim,
            "policy_terms": detail.get("policy_terms", []),
            "settlement": {"proposed": settlement.get("proposed_settlement"), "recalculated": settlement.get("payable"),
                           "difference": settlement.get("difference"), "steps": settlement.get("steps", [])},
            "findings": [{key: f.get(key) for key in keep} for f in findings],
            "related": related_claims(store=store, claim=claim, findings=findings),
            "comparison": comparison(store=store, claim=claim), "notes": detail.get("notes", []),
            "audit": [{"ts": row["ts"], "actor": row["actor"], "action": row["action"], "details": row.get("details")}
                      for row in detail.get("audit", [])]}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "<p class='muted'>None.</p>"
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


CSS = """body{font-family:Georgia,serif;color:#1a1a1a;background:#fff;max-width:960px;margin:24px auto;padding:0 16px;font-size:13px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;border-bottom:1px solid #999;padding-bottom:3px;margin-top:22px}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#f2f2f2}.muted{color:#666}.finding{border:1px solid #ccc;padding:8px;margin:8px 0;page-break-inside:avoid}
@media print{body{margin:0}}"""


def render_html(report: Dict[str, Any]) -> str:
    claim, cur = report["claim"], report["claim"].get("currency", "")
    s = report["settlement"]
    parts = [f"<h1>Investigation report: {_e(claim['claim_id'])}</h1>",
             f"<p class='muted'>Generated {_e(report['generated_at'])} by {_e(report['generated_by'])}</p>",
             "<h2>Claim</h2>",
             _table(["Field", "Value"], [[k, claim.get(k)] for k in (
                 "claimant_name", "claimant_id", "policy_number", "provider_name", "claim_type", "incident_date",
                 "admission_date", "discharge_date", "diagnosis", "requested_amount", "proposed_settlement", "currency", "status")]),
             "<h2>Policy terms</h2>",
             _table(["Term", "Value", "Clause"], [[t["term"], t["value"], t.get("clause_id")] for t in report["policy_terms"]]),
             "<h2>Settlement</h2>",
             _table(["Proposed", "Recalculated", "Difference"], [[s["proposed"], s["recalculated"], s["difference"]]]),
             "<ol>" + "".join(f"<li>{_e(step)}</li>" for step in s["steps"]) + "</ol>",
             f"<h2>Findings ({len(report['findings'])})</h2>"]
    for f in report["findings"]:
        correction = f.get("correction") or {}
        original = f.get("original") or {}
        history = f.get("decision_history") or []
        parts.append(
            "<div class='finding'>"
            f"<b>{_e(f['check_id'])}</b> &middot; {_e(f['severity'])} &middot; {_e(cur)} {_e(f['amount'])} ({_e(f['amount_kind'])})"
            f" &middot; status <b>{_e(f['status'])}</b><br>{_e(f.get('reason'))}<br>"
            f"<span class='muted'>Rule {_e(f.get('rule_id'))}: {_e(f.get('rule_text'))} {_e(f.get('calculation'))}</span>"
            + (f"<br>Correction: {_e(correction.get('label'))} &mdash; {_e(correction.get('calculation'))}" if correction else "")
            + (f"<br>AI recommendation: {_e(f.get('recommendation'))} &mdash; {_e(f.get('recommendation_note'))}" if f.get("recommendation") else "")
            + (f"<br>As raised: {_e(original.get('amount'))} ({_e(original.get('status'))}), captured {_e(original.get('captured_at'))}" if original else "")
            + (_table(["When", "By", "Action", "From", "To", "Reason", "Amount"],
                      [[h.get("ts"), h.get("by"), h.get("action"), h.get("from_status"), h.get("to_status"), h.get("reason"),
                        h.get("amount")] for h in history]) if history else "")
            + "</div>")
    parts += ["<h2>Related claims</h2>",
              _table(["Claim", "Source", "Strength", "Member", "Provider", "Date", "Links"],
                     [[r["claim_id"], r["source"], r["strength"], r.get("claimant_id"), r.get("provider_name") or r.get("provider_id"),
                       r.get("incident_date"), "; ".join(f"{m['label']} ({m['value']})" for m in r["matches"])]
                      for r in report["related"]]),
              "<h2>Documents vs claim</h2>",
              _table(["Field", "Claim", "Document", "Status"],
                     [[f["label"], f["claim_value"], f["document_value"], f["status"]] for f in report["comparison"]["fields"]]),
              _table(["Line", "Code", "Claim", "Document", "Status"],
                     [[l["description"], l["code"], l["claim_amount"], l["document_amount"], l["status"]]
                      for l in report["comparison"]["lines"]]),
              "<h2>Notes</h2>",
              _table(["When", "Author", "Note"], [[n["ts"], n["author"], n["text"]] for n in report["notes"]]),
              "<h2>Audit trail</h2>",
              _table(["When", "User", "Action"], [[a["ts"], a["actor"], a["action"]] for a in report["audit"]])]
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Investigation {_e(claim['claim_id'])}</title>"
            f"<style>{CSS}</style></head><body>{''.join(parts)}</body></html>")
