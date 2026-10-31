"""Build the demo upload folder: the files a reviewer drags onto the Ingest screen, in the formats the brief
lists (Excel, CSV, JSON), plus one file with deliberate errors to show the validation report.

    python -m scripts.make_demo_upload --out ../demo_upload
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "out"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT.parent / "demo_upload"))
    args = parser.parse_args()
    dest = Path(args.out)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for name in ("products.json", "policies.json", "providers.csv", "claimants.csv", "invoice_lines.csv", "history.json"):
        shutil.copy2(OUT / name, dest / name)

    claims = pd.read_csv(OUT / "claims.csv", dtype=str, keep_default_na=False)
    with pd.ExcelWriter(dest / "claims.xlsx") as writer:  # claims only, so no other sheet is read as a table
        claims.to_excel(writer, sheet_name="claims", index=False)

    # Three bad rows: each problem is reported by row and field and nothing is stored (a copied good row would
    # rightly be flagged as a duplicate claim and blur the live score).
    bad = claims.iloc[[1, 2, 3]].copy()
    bad["claim_id"] = ["", "CLM-2026-9002", "CLM-2026-9003"]
    bad.iloc[1, bad.columns.get_loc("requested_amount")] = "twelve hundred"
    bad.iloc[2, bad.columns.get_loc("incident_date")] = "2026-13-45"
    bad.to_csv(dest / "claims_with_errors.csv", index=False)

    docs = dest / "documents"
    docs.mkdir()
    for pdf in sorted((OUT / "documents" / "CLM-2026-0033").glob("*.pdf")):
        shutil.copy2(pdf, docs / pdf.name)
    print(f"demo upload folder: {dest}")
    for p in sorted(dest.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(dest)}  ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
