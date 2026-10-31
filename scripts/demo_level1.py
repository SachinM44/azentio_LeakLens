"""Level 1 journey through the API, end to end, printed as it happens:
ingest the synthetic files -> run every claim -> dashboard -> one flagged claim with its findings -> a review action.

    python -m scripts.demo_level1 --api http://localhost:8000 --key leaklens-dev [--limit 125]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "out"
# The documents manifest and the rendered PDFs are picked up from disk by the ingest of claims.csv (synthetic set).
UPLOADS = ["products.json", "policies.json", "providers.csv", "claimants.csv", "claims.csv", "invoice_lines.csv",
           "history.json"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--key", default="leaklens-dev")
    parser.add_argument("--limit", type=int, default=125)
    parser.add_argument("--claim", default="CLM-2026-0033", help="claim to open in the walkthrough")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.api, headers={"X-API-Key": args.key}, timeout=600)

    print("1. health:", client.get("/health").json())

    files = [("files", (name, (OUT / name).read_bytes())) for name in UPLOADS if (OUT / name).exists()]
    started = time.monotonic()
    r = client.post("/ingest", files=files)
    r.raise_for_status()
    report = r.json()
    print(f"2. ingest: {report.get('claims_created')} claims created in {time.monotonic() - started:.1f}s; "
          f"validation issues: {len(report.get('validation', []))}")
    for issue in report.get("validation", [])[:5]:
        print("   ", issue)

    claims = client.get("/claims").json()
    print(f"3. claims listed: {len(claims)}")
    started = time.monotonic()
    for row in claims[: args.limit]:
        client.post(f"/claims/{row['claim_id']}/run").raise_for_status()
    print(f"   runs started for {min(len(claims), args.limit)} claims in {time.monotonic() - started:.1f}s")
    ids = [row["claim_id"] for row in claims[: args.limit]]
    for _ in range(600):
        states = {cid: client.get(f"/claims/{cid}/run").json().get("status") for cid in ids}
        if all(s in ("paused", "done", "failed", "completed") for s in states.values()):
            break
        time.sleep(2)
    from collections import Counter
    print(f"   runs finished in {time.monotonic() - started:.1f}s: {dict(Counter(states.values()))}")
    paused_at = Counter(client.get(f"/claims/{cid}/run").json().get("paused_at") for cid in ids if states[cid] == "paused")
    print(f"   paused at: {dict(paused_at)}")

    dash = client.get("/dashboard").json()
    print("4. dashboard:", {k: dash.get(k) for k in ("processed", "flagged", "leakage_calculated", "leakage_suspected", "awaiting_review")})
    for row in (dash.get("by_category") or [])[:6]:
        print("   ", row)

    flagged = [row for row in client.get("/claims").json() if (row.get("leakage_calculated") or 0) > 0]
    flagged.sort(key=lambda r: -(r.get("leakage_calculated") or 0))
    if not flagged:
        print("5. no flagged claims"); return
    # The brief's own example (room 2,000 over the limit x 3 days) when it is in the set, else the biggest leak.
    cid = args.claim if args.claim and any(r["claim_id"] == args.claim for r in flagged) else flagged[0]["claim_id"]
    detail = client.get(f"/claims/{cid}").json()
    print(f"5. claim {cid}: {len(detail.get('findings', []))} findings; settlement payable "
          f"{(detail.get('settlement') or {}).get('payable')} vs proposed {(detail.get('settlement') or {}).get('proposed_settlement')}")
    for f in detail.get("findings", [])[:6]:
        print(f"   - {f['check_id']:26s} {f['amount_kind']:10s} {f['currency']} {f['amount']:>10,.2f}  {f['rule_id']}  | {f.get('calculation', '')[:70]}")

    first = detail.get("findings", [{}])[0]
    if first.get("finding_id"):
        r = client.post(f"/claims/{cid}/findings/{first['finding_id']}/review", json={"action": "dismiss", "note": "demo: reviewer disagrees"})
        r.raise_for_status()
        after = r.json().get("settlement") or {}
        print(f"6. dismissed {first['finding_id']}: payable now {after.get('payable')} (audit rows: {len(client.get('/audit', params={'claim_id': cid}).json())})")
    print("7. eval:", client.get("/eval/summary").json())


if __name__ == "__main__":
    main()
