"""The document path through the API on one claim that carries scanned documents:
classify pages -> the reviewer confirms the types (human gate 1) -> digitise -> lines reconcile to the printed total
-> checks run.

    python -m scripts.demo_documents --api http://localhost:8000 --claim CLM-2026-0033
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--key", default="leaklens-dev")
    parser.add_argument("--claim", default="CLM-2026-0033")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.api, headers={"X-API-Key": args.key}, timeout=900)
    cid = args.claim

    detail = client.get(f"/claims/{cid}").json()
    print(f"1. claim {cid}: documents {[d.get('name') for d in detail.get('documents', [])]}")

    started = time.monotonic()
    r = client.post(f"/claims/{cid}/documents/classify")
    print(f"2. classify -> HTTP {r.status_code} in {time.monotonic() - started:.1f}s")
    r.raise_for_status()
    pages = client.get(f"/claims/{cid}").json().get("classification", [])
    for p in pages:
        print("   ", json.dumps({k: p.get(k) for k in ("page_id", "document_id", "page", "predicted_type", "confidence",
                                                      "confirmed_type")}, ensure_ascii=False))

    confirm = [{"page_id": p.get("page_id"), "document_type": p.get("confirmed_type") or p.get("predicted_type")} for p in pages]
    started = time.monotonic()
    r = client.post(f"/claims/{cid}/classification/confirm", json=confirm)
    print(f"3. confirm (human gate 1) -> HTTP {r.status_code} in {time.monotonic() - started:.1f}s: {r.text[:300]}")
    r.raise_for_status()

    run = {}
    for _ in range(300):
        run = client.get(f"/claims/{cid}/run").json()
        if run.get("status") in ("paused", "done", "failed", "completed") and run.get("paused_at") != "classification_gate":
            break
        time.sleep(2)
    detail = client.get(f"/claims/{cid}").json()
    doc_lines = detail.get("document_lines") or []
    print(f"4. digitised lines {len(doc_lines)}; printed_total {detail.get('printed_total')}; reconciled {detail.get('reconciled')}")
    print("   facts:", json.dumps(detail.get("document_facts"), ensure_ascii=False)[:300])
    for l in doc_lines[:8]:
        print(f"   #{l.get('serial_no')} {str(l.get('description'))[:38]:38s} qty {l.get('quantity')} rate {l.get('unit_price')} = {l.get('amount')}")
    print(f"5. run {run.get('status')} paused_at {run.get('paused_at')}; cost ${run.get('cost_usd', 0):.3f}; retrieval {run.get('retrieval_mode')}")
    for f in detail.get("findings", [])[:8]:
        clause = f.get("clause") or {}
        print(f"   - {f['check_id']:22s} {f['amount_kind']:10s} {f['amount']:>10,.2f} | {f.get('calculation', '')[:60]}"
              + (f" | clause {clause.get('clause_id')} ({clause.get('score')})" if clause else ""))


if __name__ == "__main__":
    main()
