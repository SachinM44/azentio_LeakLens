# Milestone 2 — Investigate claims, compare evidence and recommend corrections

What the brief asks, what LeakLens does, and where to see it.

| # | Required capability | How LeakLens meets it | Where to look |
|---|---|---|---|
| 1 | Cross-claim correlation: related claims shown together with the attributes that connect them | Every claim lists the claims and earlier paid claims it is linked to, with the matching attributes (same invoice number under another policy, same phone or bank account across different members, same address, same member and hospital within 30 days) and a strength | Claim → **Related claims** |
| 2 | Document and invoice analysis: extract from documents, compare with the claim record, keep the source of every value | The AI reads the uploaded bill and discharge summary (native PDFs as text, photos as images) and the system compares them with the claim record: each field (patient, policy number, hospital, admission, discharge, invoice number, total) and each bill line, with the document and page it came from | Claim → **Document comparison** |
| 3 | Investigation workspace | One page per claim: the claim, the policy terms that apply, related claims, extracted document evidence, the discrepancies, the calculated leakage, the settlement and the analyst's notes | Claim page tabs |
| 4 | Recommended settlement corrections with original amount, corrected amount, calculation and policy rule | Every finding carries a correction such as "Cap the room charge at the daily limit: ₹15,000 → ₹9,000", with the calculation, the rule and the policy clause | Findings → **Recommended correction** |
| 5 | Analyst decisions | Accept correction · Confirm discrepancy · False positive (reason required) · Request evidence · Escalate to a senior claims reviewer or the Special Investigation Unit · Correct the amount (reason required) | Findings card buttons |
| 6 | Evidence and audit trail, downloadable report | Every calculation, finding, AI recommendation, decision, reason, timestamp and analyst name is recorded; the first recommendation is frozen when an analyst overrides it; the full investigation downloads as JSON or prints as a report | **Audit** tab · **Download report** |
| + | Mentor: faster AI over uploaded files | Native PDFs go to the model as text, photos as images, every page in parallel, on the faster model; seconds per claim are recorded on the run (see `docs/SPEED.md`) | Document comparison header |
| + | Mentor: customers can upload claims | Customer portal: submit a claim with its documents and follow it live (received → reading documents → checking → under review); it appears in the analyst queue at once | `/submit` |

Checked by `scripts/e2e_check.py` (Level 1) and `scripts/e2e_level2.py` (Level 2) against the running system.
