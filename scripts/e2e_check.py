"""End-to-end check of every endpoint the UI uses, on the demo upload folder, printed as PASS / FAIL.

    python -m scripts.e2e_check --api http://localhost:5173/api      # through the UI's proxy
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, List, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[1]
UPLOAD = ROOT.parent / "demo_upload"
RESULTS: List[Tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    return bool(ok)


def guarded(name: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a failing step is reported, the run goes on
        check(name, False, f"{type(exc).__name__}: {str(exc)[:200]}")
        return None


def wait_runs(client: httpx.Client, ids: List[str], timeout_s: int = 900) -> Counter:
    deadline = time.monotonic() + timeout_s
    states: dict = {}
    while time.monotonic() < deadline:
        states = {cid: client.get(f"/claims/{cid}/run").json().get("status") for cid in ids}
        if all(s in ("paused", "done", "failed", "completed") for s in states.values()):
            break
        time.sleep(3)
    return Counter(states.values())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:5173/api")
    parser.add_argument("--key", default="leaklens-dev")
    parser.add_argument("--documents-claim", default="CLM-2026-0033")
    parser.add_argument("--upload", default=str(UPLOAD), help="folder of files to ingest (default: demo_upload)")
    args = parser.parse_args()
    c = httpx.Client(base_url=args.api, headers={"X-API-Key": args.key}, timeout=900)

    check("health", c.get("/health").status_code == 200)
    check("auth: key required", httpx.get(f"{args.api}/claims", timeout=30).status_code == 401)

    # 1. Ingest exactly what a person drags in.
    upload = Path(args.upload)
    files = [("files", (p.name, p.read_bytes())) for p in sorted(upload.iterdir()) if p.is_file() and not p.name.startswith("~$")]
    files += [("files", (p.name, p.read_bytes())) for p in sorted((upload / "documents").glob("*.*"))]
    started = time.monotonic()
    r = c.post("/ingest", files=files)
    rep = r.json() if r.status_code == 200 else {}
    rejected = [v for v in rep.get("validation", []) if not v.get("accepted")]
    check("ingest", r.status_code == 200 and rep.get("claims_created") == 125,
          f"{rep.get('claims_created')} claims, {len(rep.get('documents') or [])} documents, {time.monotonic() - started:.1f}s")
    check("ingest: broken rows reported, not stored", len(rejected) == 3 and all(v.get("row") for v in rejected),
          "; ".join(f"row {v['row']} {v['field']}" for v in rejected))

    rows = c.get("/claims").json()
    check("claims list", len(rows) == 125, f"{len(rows)} rows")

    # 2. Run every claim (the Ingest screen's "Run checks").
    ids = [row["claim_id"] for row in rows]
    started = time.monotonic()
    for cid in ids:
        c.post(f"/claims/{cid}/run")
    states = wait_runs(c, ids)
    check("run all claims", states.get("failed", 0) == 0 and sum(states.values()) == 125,
          f"{dict(states)} in {time.monotonic() - started:.0f}s")

    # 3. Dashboard and filters.
    dash = c.get("/dashboard").json()
    planted = c.get("/eval/summary").json().get("amount_planted") or 0  # planted calculated leakage, in the dashboard currency
    check("dashboard totals", dash.get("processed") == 125 and abs((dash.get("leakage_calculated") or 0) - planted) < 1,
          f"processed {dash.get('processed')}, flagged {dash.get('flagged')}, calculated {dash.get('leakage_calculated')}, "
          f"suspected {dash.get('leakage_suspected')}, awaiting review {dash.get('awaiting_review')}")
    for label, params in [("category=duplicate", {"category": "duplicate"}), ("type=outpatient", {"type": "outpatient"}),
                          ("provider=P-007", {"provider": "P-007"}), ("min_amount=50000", {"min_amount": 50000}),
                          ("incident May-Jun", {"from": "2026-05-01", "to": "2026-06-30"})]:
        sub = c.get("/claims", params=params).json()
        d2 = c.get("/dashboard", params=params).json()
        check(f"filter {label}", 0 < len(sub) < 125 and d2.get("processed") == len(sub), f"{len(sub)} claims")

    # 4. The brief's example claim: finding, clause, documents, settlement.
    cid = args.documents_claim
    det = c.get(f"/claims/{cid}").json()
    room = [f for f in det.get("findings", []) if f["check_id"] == "ROOM_LIMIT_EXCEEDED"]
    check("finding: room limit 6,000 calculated", bool(room) and abs(room[0]["amount"] - 6000) < 0.01 and room[0]["amount_kind"] == "calculated",
          room[0]["calculation"] if room else "missing")
    check("finding: policy clause attached", bool(room) and bool(room[0].get("clause")),
          f"clause {(room[0].get('clause') or {}).get('clause_id')} score {(room[0].get('clause') or {}).get('score')}" if room else "")
    check("settlement present", bool(det.get("settlement")),
          f"payable {(det.get('settlement') or {}).get('payable')} vs proposed {(det.get('settlement') or {}).get('proposed_settlement')}")
    docs = det.get("documents", [])
    check("documents attached", len(docs) >= 2, ", ".join(f"{d.get('name')} ({d.get('pages')}p)" for d in docs))
    if docs:
        doc_id = docs[0].get("document_id") or docs[0].get("id")
        r = c.get(f"/documents/{doc_id}")
        check("document viewer stream", r.status_code == 200 and len(r.content) > 1000, f"{r.headers.get('content-type')} {len(r.content)} bytes")
    run = c.get(f"/claims/{cid}/run").json()
    check("policy retrieval mode", run.get("retrieval_mode") in ("embeddings", "bm25"), str(run.get("retrieval_mode")))

    # 5. AI: classify the pages, confirm (human gate 1), digitise, reconcile.
    started = time.monotonic()
    r = c.post(f"/claims/{cid}/documents/classify")
    pages = c.get(f"/claims/{cid}").json().get("classification", []) if r.status_code == 200 else []
    check("AI classify pages", r.status_code == 200 and len(pages) >= 3,
          f"{len(pages)} pages in {time.monotonic() - started:.0f}s: " + ", ".join(str(p.get("predicted_type")) for p in pages))
    if pages:
        started = time.monotonic()
        body = [{"page_id": p.get("page_id"), "document_type": p.get("predicted_type")} for p in pages]
        r = c.post(f"/claims/{cid}/classification/confirm", json=body)
        wait_runs(c, [cid])
        det = c.get(f"/claims/{cid}").json()
        lines = det.get("document_lines") or []
        check("AI digitise bill (after human confirm)", r.status_code == 200 and len(lines) > 0,
              f"{len(lines)} lines read in {time.monotonic() - started:.0f}s; printed total {det.get('printed_total')}")
        check("extracted lines reconcile to the printed total", det.get("reconciled") is True, f"reconciled={det.get('reconciled')}")

    # 6. AI investigator on suspected findings.
    flagged = [row for row in c.get("/claims").json() if (row.get("leakage_suspected") or 0) > 0]
    with_rec = None
    for row in flagged[:40]:
        fs = c.get(f"/claims/{row['claim_id']}").json().get("findings", [])
        recs = [f for f in fs if f.get("recommendation")]
        if recs:
            with_rec = (row["claim_id"], recs[0])
            break
    check("AI investigator recommendation on a suspected finding", with_rec is not None,
          f"{with_rec[0]} {with_rec[1]['check_id']}: {with_rec[1]['recommendation']} ({with_rec[1].get('recommendation_confidence')}) "
          f"- {with_rec[1].get('recommendation_note', '')[:90]}" if with_rec else "none found")

    # 7. Review actions move money and write audit rows; then the claim is re-run to restore the demo state.
    target = next((row["claim_id"] for row in c.get("/claims").json() if (row.get("leakage_calculated") or 0) > 0
                   and row["claim_id"] != cid), None)
    if target:
        det = c.get(f"/claims/{target}").json()
        fs = [f for f in det["findings"] if f["amount_kind"] == "calculated" and f["amount"] > 0]
        before = det["settlement"]["payable"]
        audit_before = len(c.get("/audit", params={"claim_id": target}).json())
        f0 = fs[0]
        r = c.post(f"/claims/{target}/findings/{f0['finding_id']}/review", json={"action": "dismiss", "note": "e2e"})
        after = (r.json().get("settlement") or {}).get("payable") if r.status_code == 200 else None
        check("review: dismiss moves the money back", r.status_code == 200 and after is not None and after > before,
              f"{target} payable {before} -> {after}")
        r = c.post(f"/claims/{target}/findings/{f0['finding_id']}/review", json={"action": "correct", "amount": round(f0['amount'] / 2, 2), "note": "e2e"})
        check("review: correct", r.status_code == 200, f"HTTP {r.status_code}")
        r = c.post(f"/claims/{target}/findings/{f0['finding_id']}/review", json={"action": "clarify", "note": "e2e"})
        check("review: request clarification", r.status_code == 200, f"HTTP {r.status_code}")
        r = c.post(f"/claims/{target}/findings/{f0['finding_id']}/review", json={"action": "confirm", "note": "e2e"})
        check("review: confirm", r.status_code == 200, f"HTTP {r.status_code}")
        audit_after = len(c.get("/audit", params={"claim_id": target}).json())
        check("audit rows written", audit_after >= audit_before + 4, f"{audit_before} -> {audit_after}")
        c.post(f"/claims/{target}/run")
        wait_runs(c, [target])

    # 8. Config.
    cfg = c.get("/config/IN-HEALTH-RETAIL")
    check("config get", cfg.status_code == 200, f"{len((cfg.json() or {}).get('non_payable_items', []))} non-payable items")
    r = c.put("/config/IN-HEALTH-RETAIL", json=cfg.json())
    check("config put", r.status_code == 200, f"HTTP {r.status_code}")

    # 9. Live score.
    ev = c.get("/eval/summary").json()
    overall = ev.get("overall") or {}
    check("live score vs answer key", (overall.get("precision") or 0) >= 0.95 and (overall.get("recall") or 0) >= 0.95,
          f"precision {overall.get('precision')} recall {overall.get('recall')}; look-alikes flagged {len(ev.get('look_alikes_wrongly_flagged') or [])}")

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
