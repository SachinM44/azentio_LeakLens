"""What a reviewer does at the demo: edit the Excel / CSV, upload again, re-run, and see the result change.

1. Copy claim CLM-2026-0001's invoice number onto CLM-2026-0011 (same clinic, another member, another policy)
   -> Related claims links the two by "Same invoice number" and a suspected duplicate-claim finding appears.
2. Raise a room line above the policy's daily limit on a clean claim
   -> a calculated room-limit finding with the exact excess.

    python -m scripts.e2e_excel_edits --api http://localhost:8023 --upload <clean upload folder>
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import httpx
import pandas as pd


def wait_run(c: httpx.Client, cid: str) -> dict:
    for _ in range(120):
        run = c.get(f"/claims/{cid}/run").json()
        if run.get("status") in ("paused", "completed", "failed"):
            return run
        time.sleep(1)
    return run


def run_claims(c: httpx.Client, ids: list) -> None:
    for cid in ids:
        c.post(f"/claims/{cid}/run")
    for cid in ids:
        wait_run(c, cid)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8023")
    parser.add_argument("--key", default="leaklens-dev")
    parser.add_argument("--upload", required=True)
    args = parser.parse_args()
    up = Path(args.upload)
    c = httpx.Client(base_url=args.api, headers={"X-API-Key": args.key, "X-Analyst": "excel test"}, timeout=300)
    ok_all = True

    names = ["products.json", "policies.json", "providers.csv", "claimants.csv", "claims.xlsx", "invoice_lines.csv", "history.json"]
    r = c.post("/ingest", files=[("files", (n, (up / n).read_bytes())) for n in names])
    print("base ingest:", r.json().get("claims_created"), "claims")
    run_claims(c, [row["claim_id"] for row in c.get("/claims").json()])

    # 1. Same invoice under another policy (the brief's own example)
    claims = pd.read_excel(up / "claims.xlsx", sheet_name="claims", dtype=str, keep_default_na=False)
    src = claims.loc[claims.claim_id == "CLM-2026-0001", "invoice_numbers"].iloc[0]
    claims.loc[claims.claim_id == "CLM-2026-0011", "invoice_numbers"] = src
    buf = io.BytesIO()
    claims.to_excel(buf, sheet_name="claims", index=False)
    r = c.post("/ingest", files=[("files", ("claims.xlsx", buf.getvalue()))])
    rep = r.json()
    print(f"edited Excel uploaded: {rep.get('claims_created')} new, {len(rep.get('claims_affected') or [])} updated")
    run_claims(c, ["CLM-2026-0011"])
    rel = c.get("/claims/CLM-2026-0011/related").json()
    link = [x for x in rel.get("related", []) if x["claim_id"] == "CLM-2026-0001"]
    labels = [m["label"] for m in (link[0]["matches"] if link else [])]
    finding = [f for f in c.get("/claims/CLM-2026-0011").json()["findings"] if f["check_id"] == "DUPLICATE_CLAIM"]
    ok = bool(link) and any("invoice" in l.lower() for l in labels) and bool(finding)
    ok_all &= ok
    print(("PASS" if ok else "FAIL"), "same invoice under another policy:", labels,
          "|", (f"{finding[0]['amount_kind']} {finding[0]['currency']} {finding[0]['amount']}: {finding[0]['reason']}" if finding else "no finding"))

    # 2. Room charge above the daily limit on a clean claim
    lines = pd.read_csv(up / "invoice_lines.csv", dtype=str, keep_default_na=False)
    target = None
    for cid in [row["claim_id"] for row in c.get("/claims").json()]:
        d = c.get(f"/claims/{cid}").json()
        if d["claim"]["currency"] != "INR" or d["findings"] or not d.get("policy"):
            continue
        limit = d["policy"].get("room_rent_limit_per_day")
        rooms = [l for l in d["lines"] if (l.get("category") == "room") and l.get("unit_price")]
        if limit and rooms:
            target = (cid, rooms[0], float(limit))
            break
    if not target:
        print("FAIL no clean claim with a room line found"); sys.exit(1)
    cid, room, limit = target
    new_rate = limit + 2000
    qty = float(room["quantity"])
    mask = lines.line_id == room["line_id"]
    lines.loc[mask, "unit_price"] = f"{new_rate:.2f}"
    lines.loc[mask, "amount"] = f"{new_rate * qty:.2f}"
    buf = io.StringIO()
    lines[mask].to_csv(buf, index=False)
    r = c.post("/ingest", files=[("files", ("invoice_lines.csv", buf.getvalue().encode("utf-8")))])
    print(f"edited CSV uploaded (1 row): {len(r.json().get('claims_affected') or [])} claim updated")
    run_claims(c, [cid])
    rooms = [f for f in c.get(f"/claims/{cid}").json()["findings"] if f["check_id"] == "ROOM_LIMIT_EXCEEDED"]
    expected = 2000 * qty
    ok = bool(rooms) and abs(rooms[0]["amount"] - expected) < 0.01
    ok_all &= ok
    print(("PASS" if ok else "FAIL"), f"room raised to {new_rate:,.0f}/day on {cid}:",
          (f"{rooms[0]['amount']:,.2f} calculated = {rooms[0]['calculation']}" if rooms else "no finding"), f"(expected {expected:,.2f})")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
