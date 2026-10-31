"""Time page classification + digitisation on two synthetic claims, with real model calls (fresh cache each run).

    .venv/Scripts/python.exe scripts/time_documents.py --label before --model bedrock/moonshotai.kimi-k2.5 --no-text-layer
    .venv/Scripts/python.exe scripts/time_documents.py --label after

(a) CLM-2026-0033: native PDFs (bill + discharge summary); ground truth 29 charge lines = 76,024, net payable 76,024.
(b) CLM-2026-0032: two phone photos of the bill (no text layer).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO.parent / "demo_upload" / "documents"
SETS = {"CLM-2026-0033": ["CLM-2026-0033_bill.pdf", "CLM-2026-0033_discharge_summary.pdf"],
        "CLM-2026-0032": ["CLM-2026-0032_bill_scan_p1.jpg", "CLM-2026-0032_bill_scan_p2.jpg"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--model", default=None, help="LEAKLENS_DOC_MODEL for this run")
    parser.add_argument("--no-text-layer", action="store_true", help="send every page as an image")
    parser.add_argument("--only", default=None, help="one claim id")
    args = parser.parse_args()
    if args.model:
        os.environ["LEAKLENS_DOC_MODEL"] = args.model
    os.environ["LEAKLENS_TEXT_LAYER"] = "0" if args.no_text_layer else "1"
    sys.path.insert(0, str(REPO))
    from core.documents import pipeline
    from core.documents.pipeline import classify_pages, digitise_documents, file_types, make_ask
    from core.llm.client import PRIMARY_MODEL, CostMeter
    doc_model = getattr(pipeline, "doc_model", lambda: PRIMARY_MODEL)
    from core.media.pages import load_file_pages

    import litellm  # noqa: F401 - imported before the clock starts (the server imports it once at its first call)

    out = {"label": args.label, "model": doc_model(), "text_layer": not args.no_text_layer, "claims": {}}
    for claim_id, names in SETS.items():
        if args.only and claim_id != args.only:
            continue
        cache = Path(tempfile.mkdtemp(prefix=f"time_{claim_id}_"))
        meter = CostMeter(cap_usd=5)
        ask = make_ask(cache, meter)
        t0 = time.monotonic()
        pages = [p for name in names for p in load_file_pages(DOCS / name)]
        t1 = time.monotonic()
        predictions = classify_pages(pages, ask, bundle_name=f"{claim_id}.pdf")
        t2 = time.monotonic()
        types = file_types(predictions)
        result = digitise_documents(pages, types, ask, claim_id=claim_id)
        t3 = time.monotonic()
        total = round(sum(line.amount for line in result.lines) + sum(float(r.get("total_amount") or 0) for r in result.discount_rows), 2)
        out["claims"][claim_id] = {
            "pages": len(pages), "load_s": round(t1 - t0, 2), "classify_s": round(t2 - t1, 2), "digitise_s": round(t3 - t2, 2),
            "total_s": round(t3 - t0, 2), "types": types, "min_confidence": round(min(p.confidence for p in predictions), 3),
            "lines": len(result.lines), "lines_total": total, "printed_total": result.printed_total,
            "reconciled": result.reconciled, "cost_usd": round(meter.spent_usd, 4),
            "models": sorted({c.model for c in result.calls}),
            "pages_sent_as_text": 0 if args.no_text_layer else sum(1 for p in pages if getattr(p, "text", "")),
        }
        print(json.dumps({claim_id: out["claims"][claim_id]}), flush=True)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
