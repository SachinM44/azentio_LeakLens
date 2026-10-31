"""Browser check of the review console (headless Chromium): every screen and claim tab renders without a page
error, the Level 2 tabs show their content, an analyst decision works from the UI, the report downloads and the
customer portal takes a claim end to end. Screenshots go to --shots.

    python -m scripts.ui_check --ui http://localhost:5173 --shots <folder>
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "demo_upload" / "documents"
RESULTS: List[Tuple[str, bool, str]] = []
ERRORS: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    return bool(ok)


def errors_since(mark: int) -> List[str]:
    return [e for e in ERRORS[mark:] if "favicon" not in e]


def visit(page: Page, url: str, name: str, shots: Path, expect: str) -> None:
    mark = len(ERRORS)
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(800)
    body = page.inner_text("body")
    page.screenshot(path=str(shots / f"{name}.png"), full_page=False)
    errs = errors_since(mark)
    check(f"screen {name}", expect.lower() in body.lower() and not errs, (errs[0][:160] if errs else f"shows '{expect}'"))


def tab(page: Page, label: str, name: str, shots: Path, expect: str) -> None:
    mark = len(ERRORS)
    page.get_by_role("tab", name=re.compile(rf"^{re.escape(label)}")).click()
    page.wait_for_timeout(1200)
    panel = page.locator(".ant-tabs-tabpane-active").inner_text()
    page.screenshot(path=str(shots / f"{name}.png"), full_page=False)
    errs = errors_since(mark)
    check(f"tab {name}", (expect.lower() in panel.lower()) and not errs, (errs[0][:160] if errs else f"'{expect}' visible"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", default="http://localhost:5173")
    parser.add_argument("--shots", default=str(ROOT / "ui_shots"))
    args = parser.parse_args()
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, accept_downloads=True)
        context.add_init_script("try { localStorage.setItem('leaklens_analyst', 'UI check'); } catch (e) {}")
        page = context.new_page()
        page.on("pageerror", lambda e: ERRORS.append(f"pageerror: {e}"))
        page.on("console", lambda m: ERRORS.append(f"console: {m.text}") if m.type == "error" else None)
        ui = args.ui.rstrip("/")

        visit(page, f"{ui}/dashboard", "dashboard", shots, "Claims processed")
        visit(page, f"{ui}/claims", "claims", shots, "CLM-2026-")
        visit(page, f"{ui}/ingest", "ingest", shots, "Drop files here")
        visit(page, f"{ui}/config", "config", shots, "HEALTH-")

        visit(page, f"{ui}/claims/CLM-2026-0033", "claim_0033", shots, "CLM-2026-0033")
        for label, expect in [("Findings", "Recommended correction"), ("Settlement", "Recalculated"), ("Master data", "Invoice lines"),
                              ("Policy terms", "Annual limit"), ("Related claims", "CLM-"), ("Document comparison", "Claim total"),
                              ("Documents", "CLM-2026-0033_bill.pdf"), ("Classification", "Itemized"), ("Notes", "note"), ("Audit", "run")]:
            tab(page, label, f"0033_{label.lower().replace(' ', '_')}", shots, expect)
        page.goto(f"{ui}/claims/CLM-2026-0033", wait_until="networkidle")  # back to the default Findings tab
        page.wait_for_timeout(800)
        room = page.locator("text=Cap the room charge").first
        check("finding card shows the room correction", room.count() > 0 and room.is_visible(),
              page.locator("text=15,000").first.inner_text()[:60] if page.locator("text=15,000").count() else "15,000 not shown")

        visit(page, f"{ui}/claims/CLM-2026-0079", "claim_0079", shots, "CLM-2026-0079")
        tab(page, "Related claims", "0079_related", shots, "invoice")
        visit(page, f"{ui}/claims/CLM-2026-0037", "claim_0037", shots, "CLM-2026-0037")
        tab(page, "Document comparison", "0037_comparison", shots, "mismatch")

        # A decision from the UI: false positive needs a reason, then shows on the card.
        visit(page, f"{ui}/claims/CLM-2026-0016", "claim_0016", shots, "CLM-2026-0016")
        mark = len(ERRORS)
        page.get_by_role("button", name=re.compile("False positive")).first.click()
        page.wait_for_timeout(500)
        modal = page.locator(".ant-modal-content").last
        modal.locator("textarea, input").first.fill("Included in the surgical package (UI check)")
        modal.locator(".ant-btn-primary").last.click()
        page.wait_for_timeout(2000)
        page.screenshot(path=str(shots / "0016_false_positive.png"), full_page=False)
        body = page.inner_text("body")
        check("decision from the UI: false positive with reason", "surgical package" in body and not errors_since(mark),
              "reason shown on the card" if "surgical package" in body else "reason not visible")

        # Report download from the claim header.
        try:
            with page.expect_download(timeout=20000) as dl:
                page.get_by_role("button", name=re.compile("Download report")).click()
            saved = shots / dl.value.suggested_filename
            dl.value.save_as(str(saved))
            check("report download", saved.stat().st_size > 1000, f"{saved.name} {saved.stat().st_size} bytes")
        except Exception as exc:  # noqa: BLE001
            check("report download", False, str(exc)[:160])

        # Customer portal end to end.
        mark = len(ERRORS)
        page.goto(f"{ui}/submit", wait_until="networkidle")
        def field(label: str):
            return page.locator("label", has_text=label).locator("input").first
        field("Policy number").fill("POL-IN-0011")
        field("Member id").fill("M-0022")
        for label, value in [("Incident date", "2026-03-01"), ("Admission date", "2026-03-01"), ("Discharge date", "2026-03-04")]:
            box = field(label)
            box.click()
            box.fill(value)
            box.press("Enter")
        field("Hospital").fill("Meridian Care Hospital")
        field("Amount claimed").fill("76024")
        field("Diagnosis").fill("Acute appendicitis")
        page.locator("input[type=file]").set_input_files([str(DOCS / "CLM-2026-0033_bill.pdf"), str(DOCS / "CLM-2026-0033_discharge_summary.pdf")])
        page.wait_for_timeout(500)
        page.screenshot(path=str(shots / "portal_form.png"), full_page=True)
        started = time.monotonic()
        page.get_by_role("button", name=re.compile("Submit claim")).click()
        page.wait_for_url(re.compile(r".*/submit/CLM-P-\d+"), timeout=20000)
        check("portal: submit goes to the status page", "/submit/CLM-P-" in page.url, f"{page.url.split('/')[-1]} in {time.monotonic() - started:.1f}s")
        deadline = time.monotonic() + 240
        text = ""
        while time.monotonic() < deadline:
            text = page.inner_text("body").lower()
            if "under review" in text or "settled" in text or "failed" in text:
                break
            page.wait_for_timeout(2000)
        page.screenshot(path=str(shots / "portal_status.png"), full_page=True)
        check("portal: status reaches review", ("under review" in text or "settled" in text) and not errors_since(mark),
              f"after {time.monotonic() - started:.0f}s" + (f"; {errors_since(mark)[0][:120]}" if errors_since(mark) else ""))
        browser.close()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
