"""Level 2 end-to-end check, run after scripts/e2e_check.py has ingested and run the synthetic set:
related claims, document comparison, corrections, the five analyst decisions, notes, audit identity, the investigation
report and the customer portal. Prints PASS / FAIL per check and exits non-zero on any failure.

    python -m scripts.e2e_level2 --api http://localhost:5173/api
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "demo_upload" / "documents"
ANALYST = "e2e analyst"
RESULTS: List[Tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    return bool(ok)


def step(name: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a failing step is reported and the run goes on
        check(name, False, f"{type(exc).__name__}: {str(exc)[:220]}")
        return None


def wait_until(fn: Callable[[], Any], ok: Callable[[Any], bool], timeout_s: float, every_s: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout_s
    value = fn()
    while not ok(value) and time.monotonic() < deadline:
        time.sleep(every_s)
        value = fn()
    return value


def wait_run(c: httpx.Client, cid: str, timeout_s: float = 300) -> Dict[str, Any]:
    return wait_until(lambda: c.get(f"/claims/{cid}/run").json(),
                      lambda r: r.get("status") in ("paused", "completed", "done", "failed"), timeout_s, 2)


def related_checks(c: httpx.Client) -> None:
    rel = c.get("/claims/CLM-2026-0079/related").json()
    hits = [r for r in rel.get("related", []) if any(m.get("attribute") == "invoice_number" for m in r.get("matches", []))]
    check("related: duplicate claim shows its twin by invoice number", bool(hits),
          ", ".join(f"{r['claim_id']} ({r.get('strength')}): " + "; ".join(m.get("label", "") for m in r["matches"]) for r in hits[:2]))
    rel = c.get("/claims/CLM-2026-0007/related").json()
    ring = [r for r in rel.get("related", []) if any(m.get("attribute") in ("phone", "bank_account") for m in r.get("matches", []))]
    check("related: shared phone / bank account across members", len(ring) >= 2,
          f"{len(ring)} linked claims, e.g. " + "; ".join(m.get("label", "") for m in (ring[0]["matches"] if ring else [])))


def comparison_checks(c: httpx.Client) -> None:
    cmp37 = wait_until(lambda: c.get("/claims/CLM-2026-0037/comparison").json(), lambda r: r.get("extracted"), 300)
    mism = [f for f in cmp37.get("fields", []) if f.get("status") == "mismatch" and f.get("field") in ("policy_number", "claimant_name")]
    sourced = all((f.get("source") or {}).get("document_name") and (f.get("source") or {}).get("page") for f in mism)
    check("comparison: document vs claim mismatch with its source", bool(mism) and sourced,
          "; ".join(f"{f['label']}: claim '{f['claim_value']}' vs document '{f['document_value']}' "
                    f"({(f.get('source') or {}).get('document_name')} p{(f.get('source') or {}).get('page')})" for f in mism))
    cmp33 = wait_until(lambda: c.get("/claims/CLM-2026-0033/comparison").json(), lambda r: r.get("extracted"), 300)
    s = cmp33.get("summary") or {}
    check("comparison: 0033 lines and totals agree", s.get("lines_matched", 0) >= 29 and abs((s.get("document_total") or 0) - 76024) <= 1
          and abs((s.get("claim_total") or 0) - 76024) <= 1,
          f"matched {s.get('lines_matched')}, only-doc {s.get('lines_only_in_document')}, only-claim {s.get('lines_only_in_claim')}, "
          f"totals {s.get('claim_total')} / {s.get('document_total')}; read by {cmp33.get('extracted_by')} {cmp33.get('model')} "
          f"in {cmp33.get('read_seconds')} s")


def correction_checks(c: httpx.Client) -> None:
    det = c.get("/claims/CLM-2026-0033").json()
    room = next((f for f in det.get("findings", []) if f["check_id"] == "ROOM_LIMIT_EXCEEDED"), None)
    cor = (room or {}).get("correction") or {}
    check("correction: room 15,000 -> 9,000 with rule and clause",
          abs((cor.get("original_amount") or 0) - 15000) < 0.01 and abs((cor.get("corrected_amount") or -1) - 9000) < 0.01
          and cor.get("rule_id") == "ROOM-01" and bool(cor.get("clause_id")),
          f"{cor.get('label')}: {cor.get('original_amount')} -> {cor.get('corrected_amount')} ({cor.get('rule_id')}, clause {cor.get('clause_id')})")
    missing = [f["finding_id"] for f in det.get("findings", []) if not f.get("correction")]
    check("correction: every finding on 0033 has one", not missing, f"missing: {missing}" if missing else f"{len(det['findings'])} findings")


def decision_checks(c: httpx.Client) -> None:
    cid = "CLM-2026-0091"
    det = c.get(f"/claims/{cid}").json()
    fs = [f for f in det.get("findings", []) if f["amount_kind"] == "calculated" and f["amount"] > 0]
    if len(fs) < 3:
        check("decisions: claim with three findings", False, f"{cid} has {len(fs)}")
        return
    f0, f1, f2 = fs[0], fs[1], fs[2]
    url = lambda f: f"/claims/{cid}/findings/{f['finding_id']}/review"  # noqa: E731
    r = c.post(url(f0), json={"action": "false_positive"})
    check("decision: false positive needs a reason", r.status_code == 400, f"HTTP {r.status_code} {r.text[:80]}")
    before = det["settlement"]["payable"]
    r = c.post(url(f0), json={"action": "false_positive", "reason": "Gloves were part of the surgical package (e2e)"})
    f0a = (r.json() or {}).get("finding") or {}
    check("decision: false positive with reason", r.status_code == 200 and f0a.get("status") == "dismissed"
          and "package" in (f0a.get("decision_reason") or "") and f0a.get("decided_by") == ANALYST,
          f"status {f0a.get('status')}, by {f0a.get('decided_by')}, payable {before} -> {(r.json().get('settlement') or {}).get('payable')}")
    r = c.post(url(f1), json={"action": "escalate"})
    check("decision: escalate needs a target", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.post(url(f1), json={"action": "escalate", "escalate_to": "siu", "note": "pattern across members (e2e)"})
    f1a = (r.json() or {}).get("finding") or {}
    check("decision: escalate to SIU", r.status_code == 200 and f1a.get("status") == "escalated" and f1a.get("escalated_to") == "siu",
          f"status {f1a.get('status')} to {f1a.get('escalated_to')}")
    r = c.post(url(f2), json={"action": "accept_correction"})
    f2a = (r.json() or {}).get("finding") or {}
    check("decision: accept recommended correction", r.status_code == 200 and f2a.get("status") == "correction_accepted",
          f"status {f2a.get('status')}")
    r = c.post(url(f2), json={"action": "request_evidence", "note": "ask the hospital for the item list (e2e)"})
    check("decision: request additional evidence", r.status_code == 200 and (r.json().get("finding") or {}).get("status") == "clarification_requested")
    r = c.post(url(f2), json={"action": "confirm"})
    f2b = (r.json() or {}).get("finding") or {}
    check("decision: confirm discrepancy", r.status_code == 200 and f2b.get("status") == "confirmed")
    orig = f2b.get("original") or {}
    check("override keeps the original recommendation", orig.get("status") == "auto_applied" or orig.get("status") == "open",
          f"original status {orig.get('status')}, amount {orig.get('amount')}, correction {(orig.get('correction') or {}).get('label')}; "
          f"history {len(f2b.get('decision_history') or [])} entries")
    r = c.post(url(f0), json={"action": "correct", "amount": round(f0['amount'] / 2, 2)})
    check("decision: correct needs a reason", r.status_code == 400, f"HTTP {r.status_code}")
    audit = c.get("/audit", params={"claim_id": cid}).json()
    mine = [a for a in audit if a.get("actor") == ANALYST]
    check("audit: decisions carry the analyst name", len(mine) >= 5, f"{len(mine)} rows by '{ANALYST}' of {len(audit)}")
    overrides = [a for a in mine if (a.get("details") or {}).get("overrides_recommendation")]
    check("audit: override flagged with its reason", bool(overrides), f"{len(overrides)} override rows")
    c.post(f"/claims/{cid}/run")  # restore the demo state: a fresh run replaces the findings
    wait_run(c, cid)


def notes_and_report_checks(c: httpx.Client) -> None:
    cid = "CLM-2026-0033"
    r = c.post(f"/claims/{cid}/notes", json={"text": "Room class on the discharge summary is Single AC (e2e note)"})
    note = r.json() if r.status_code in (200, 201) else {}
    det = c.get(f"/claims/{cid}").json()
    check("notes: added and shown", note.get("author") == ANALYST and any(n.get("note_id") == note.get("note_id") for n in det.get("notes", [])),
          f"by {note.get('author')}")
    check("workspace: policy terms present", len(det.get("policy_terms") or []) >= 5, f"{len(det.get('policy_terms') or [])} terms")
    r = c.get(f"/claims/{cid}/report", params={"format": "json"})
    rep = r.json() if r.status_code == 200 else {}
    needed = ["claim", "policy_terms", "settlement", "findings", "related", "comparison", "notes", "audit"]
    missing = [k for k in needed if k not in rep]
    check("report: structured JSON has every section", r.status_code == 200 and not missing,
          f"missing {missing}" if missing else f"{len(rep.get('findings', []))} findings, {len(rep.get('audit', []))} audit rows")
    r = c.get(f"/claims/{cid}/report", params={"format": "html"})
    check("report: printable HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""), f"{len(r.text)} chars")


def portal_checks(c: httpx.Client) -> None:
    r = c.post("/portal/claims", data={"policy_number": "POL-XX-9999", "member_id": "M-0022", "claim_type": "inpatient",
                                        "incident_date": "2026-03-01", "provider_name": "Meridian Care Hospital", "amount_claimed": "100"},
               files=[("files", ("bill.pdf", (DOCS / "CLM-2026-0033_bill.pdf").read_bytes(), "application/pdf"))])
    check("portal: unknown policy rejected", r.status_code == 422, f"HTTP {r.status_code} {r.text[:100]}")
    started = time.monotonic()
    files = [("files", ("hospital_bill.pdf", (DOCS / "CLM-2026-0033_bill.pdf").read_bytes(), "application/pdf")),
             ("files", ("discharge.pdf", (DOCS / "CLM-2026-0033_discharge_summary.pdf").read_bytes(), "application/pdf"))]
    r = c.post("/portal/claims", files=files, data={
        "policy_number": "POL-IN-0011", "member_id": "M-0022", "claim_type": "inpatient", "incident_date": "2026-03-01",
        "admission_date": "2026-03-01", "discharge_date": "2026-03-04", "provider_name": "Meridian Care Hospital",
        "amount_claimed": "76024", "diagnosis": "Acute appendicitis"})
    took = time.monotonic() - started
    body = r.json() if r.status_code in (200, 201) else {}
    cid = body.get("claim_id", "")
    check("portal: claim accepted at once", r.status_code in (200, 201) and cid.startswith("CLM-P-") and took < 3,
          f"{cid} in {took:.2f}s")
    if not cid:
        return
    started = time.monotonic()
    status = wait_until(lambda: c.get(f"/portal/claims/{cid}").json(),
                        lambda s: s.get("status") in ("under_review", "settled", "waiting_for_analyst", "failed"), 300, 2)
    check("portal: documents read and checked", status.get("status") in ("under_review", "settled") and (status.get("lines_read") or 0) > 0,
          f"status {status.get('status')} after {time.monotonic() - started:.0f}s; {status.get('pages_read')} pages, "
          f"{status.get('lines_read')} lines read in {status.get('read_seconds')} s")
    det = c.get(f"/claims/{cid}").json()
    checks = sorted({f["check_id"] for f in det.get("findings", [])})
    check("portal: findings computed from the read lines", det.get("claim", {}).get("source") == "documents" and bool(checks),
          f"{len(det.get('lines', []))} lines; checks: {', '.join(checks)}")
    check("portal: claim visible in the analyst queue", any(row["claim_id"] == cid for row in c.get("/claims").json()))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:5173/api")
    parser.add_argument("--key", default="leaklens-dev")
    args = parser.parse_args()
    c = httpx.Client(base_url=args.api, headers={"X-API-Key": args.key, "X-Analyst": ANALYST}, timeout=600)
    for name, fn in [("related", related_checks), ("comparison", comparison_checks), ("corrections", correction_checks),
                     ("decisions", decision_checks), ("notes + report", notes_and_report_checks), ("portal", portal_checks)]:
        step(name, lambda fn=fn: fn(c))
    ev = c.get("/eval/summary").json().get("overall") or {}
    check("live score unchanged by Level 2", ev.get("precision") == 1.0 and (ev.get("recall") or 0) >= 0.98,
          f"precision {ev.get('precision')} recall {ev.get('recall')}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
