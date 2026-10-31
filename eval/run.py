"""Score a findings file against the synthetic answer key.

    python -m eval.run --findings <findings.json> [--key data/synthetic/out/answer_key.json] [--strict]

The findings file is a JSON list of Finding records (or {"findings": [...]}). A finding matches a planted case
when its claim_id and check_id agree with a key positive; dismissed findings do not count. Prints precision and
recall per check and overall, the calculated amount recovered against the key, and every key negative that was
wrongly flagged. Exits 1 when any planted CALCULATED case is missed; with --strict also when a calculated amount
is off by more than 1.00 or a negative was flagged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from core.schemas.finding import AmountKind, Finding, FindingStatus

AMOUNT_TOLERANCE = 1.0


def load_findings(path: Path) -> List[Finding]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("findings", [])
    findings: List[Finding] = []
    errors: List[str] = []
    for n, item in enumerate(raw):
        try:
            findings.append(Finding.model_validate(item))
        except Exception as exc:  # noqa: BLE001 - report every bad record, then stop
            errors.append(f"record {n}: {exc}")
    if errors:
        print("Findings file has records that do not match the Finding contract:")
        for e in errors[:20]:
            print("  " + e.splitlines()[0])
        sys.exit(2)
    return findings


def ratio(num: int, den: int) -> str:
    return "  -  " if den == 0 else f"{num / den:5.0%}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Score findings against the synthetic answer key")
    parser.add_argument("--findings", required=True, help="JSON list of Finding records")
    parser.add_argument("--key", default="data/synthetic/out/answer_key.json")
    parser.add_argument("--strict", action="store_true", help="also fail on amount drift or flagged negatives")
    args = parser.parse_args()

    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    positives = key["positives"]
    negatives = key["negatives"]
    findings = [f for f in load_findings(Path(args.findings)) if f.status != FindingStatus.DISMISSED]

    found: Dict[Tuple[str, str], List[Finding]] = defaultdict(list)
    for f in findings:
        found[(f.claim_id, f.check_id.value)].append(f)
    pos_keys = {(p["claim_id"], p["check_id"]): p for p in positives}
    neg_keys = {(n["claim_id"], n["check_id"]): n for n in negatives}

    checks = sorted({p["check_id"] for p in positives} | {k[1] for k in found})
    tp: Dict[str, int] = defaultdict(int)
    fp: Dict[str, int] = defaultdict(int)
    fn: Dict[str, int] = defaultdict(int)
    missed_calculated: List[dict] = []
    amount_rows: List[Tuple[str, str, float, float]] = []
    for (claim_id, check_id), row in pos_keys.items():
        hits = found.get((claim_id, check_id))
        if hits:
            tp[check_id] += 1
            if row["amount_kind"] == AmountKind.CALCULATED.value:
                got = round(sum(h.effective_amount if h.status != FindingStatus.OPEN else h.amount for h in hits), 2)
                amount_rows.append((claim_id, check_id, float(row["amount"]), got))
        else:
            fn[check_id] += 1
            if row["amount_kind"] == AmountKind.CALCULATED.value:
                missed_calculated.append(row)
    false_positives: List[Tuple[str, str]] = []
    for (claim_id, check_id) in found:
        if (claim_id, check_id) not in pos_keys:
            fp[check_id] += 1
            false_positives.append((claim_id, check_id))
    wrongly_flagged = [neg_keys[k] for k in found if k in neg_keys]

    print(f"{'check':<28} {'TP':>4} {'FP':>4} {'FN':>4} {'precision':>10} {'recall':>8}")
    for c in checks:
        print(f"{c:<28} {tp[c]:>4} {fp[c]:>4} {fn[c]:>4} {ratio(tp[c], tp[c] + fp[c]):>10} {ratio(tp[c], tp[c] + fn[c]):>8}")
    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    print(f"{'OVERALL':<28} {TP:>4} {FP:>4} {FN:>4} {ratio(TP, TP + FP):>10} {ratio(TP, TP + FN):>8}")

    key_total = sum(float(p["amount"]) for p in positives if p["amount_kind"] == AmountKind.CALCULATED.value)
    recovered = sum(min(got, want) for _, _, want, got in amount_rows)
    exact = sum(1 for _, _, want, got in amount_rows if abs(want - got) <= AMOUNT_TOLERANCE)
    drift = [(cid, chk, want, got) for cid, chk, want, got in amount_rows if abs(want - got) > AMOUNT_TOLERANCE]
    print(f"\nCalculated amount in key: {key_total:,.2f}   recovered by matched findings: {recovered:,.2f} "
          f"({ratio(int(recovered), int(key_total)).strip()})   exact amounts: {exact}/{len(amount_rows)}")
    if drift:
        print("Amount drift on matched calculated cases (claim, check, key, found):")
        for cid, chk, want, got in drift:
            print(f"  {cid} {chk}: key {want:,.2f} found {got:,.2f}")
    if missed_calculated:
        print("\nMISSED planted calculated cases:")
        for row in missed_calculated:
            print(f"  {row['claim_id']} {row['check_id']} {row['amount']:,.2f}  {row['note']}")
    if false_positives:
        print(f"\nFindings on claims/checks not in the key ({len(false_positives)}):")
        for cid, chk in sorted(false_positives)[:40]:
            print(f"  {cid} {chk}")
    if wrongly_flagged:
        print(f"\nKey NEGATIVES that were flagged ({len(wrongly_flagged)}):")
        for n in wrongly_flagged:
            print(f"  {n['claim_id']} {n['check_id']}: {n['note']}")
    else:
        print("\nNo key negative was flagged.")

    failed = bool(missed_calculated) or (args.strict and (drift or wrongly_flagged))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
