# LeakLens demo script (Milestone 1)

**What it is.** An insurer's claims team gets thousands of health claims. Some are paid wrongly: the same bill
twice, a room charge above the policy's daily limit, an excluded treatment, a copay the handler forgot. LeakLens
reads the claims, invoices, policies and claim history, finds those errors, puts an amount on each with the rule
and the evidence, and lets a claims handler confirm or dismiss each one before the money goes out.

**Start:** API `uvicorn backend.main:app --port 8000` · UI `cd ui && npm run dev` → http://localhost:5173.
The system starts empty. Upload files are in `demo_upload/` (built by `python -m scripts.make_demo_upload`).

| What is in `demo_upload/` | What it is |
|---|---|
| `products.json` | the two insurance products (India retail health in INR, UAE group health in AED): limits, required documents, non-payable lists |
| `policies.json` | 30 policies: sum insured, room limit, copay, deductible, sub-limits, exclusions with clause numbers |
| `providers.csv`, `claimants.csv` | 8 hospitals / clinics, 60 members |
| `claims.xlsx` | 125 claims (Excel): who, where, when, how much asked, how much the handler proposed to pay |
| `invoice_lines.csv` | 1,992 bill lines: description, code, qty, rate, amount, date |
| `history.json` | 40 earlier claims already paid (for duplicates and annual limits) |
| `claims_with_errors.csv` | 3 broken rows (missing id, amount "twelve hundred", date 2026-13-45) to show validation |
| `documents/` | the bill and discharge summary PDFs of claim CLM-2026-0033 |

## Five minutes, click by click

1. **Ingest** (left menu) → drag **all files of `demo_upload/`, including the two PDFs** → *Upload*.
   *Say:* "Excel, CSV, JSON and documents in one go. 125 claims created; the three broken rows are listed with row,
   field and the problem — rejected and reported, never silently dropped." → click **Run checks**.
2. **Dashboard**. *Say:* "Every claim was checked against its policy, its history and the other claims. Calculated
   leakage is exact by rule; suspected leakage is a pattern that needs a person — the two are never added together."
   Point at the category donut, the severity bar, the filters.
3. **Claims** → filter *Leakage category = Policy rules* → open **CLM-2026-0033**.
   **Findings** tab: the room card — *Calculated* · rule ROOM-01 · "(5,000 − 3,000) × 3 days = 6,000" (the brief's own
   example) · the policy clause. **Documents** tab: open the bill PDF — the same room line is on it.
4. **Settlement** tab: requested → deductions by rule → copay → payable, and *proposed vs recalculated*.
   Back on **Findings**, **Dismiss** one finding with a note → the payable goes back up → **Audit** tab shows who did what.
5. Show one of each scenario the brief lists:

| Brief scenario | Claim | What you see |
|---|---|---|
| Exact duplicate claim | CLM-2026-0079 | same invoice already submitted; 24,168 calculated |
| Duplicate line | CLM-2026-0067 | "Liver Function Test" and "LFT" on the same day; 840 |
| Near-duplicate (review) | CLM-2026-0009 | +1 day, +2 %, new invoice number; suspected |
| Legitimate repeat (no flag) | CLM-2026-0040 | 6 physiotherapy sessions on 6 dates: **nothing flagged** |
| Excluded service | CLM-2026-0016 | dental, clause 10.4; 6,650 |
| Sub-limit | CLM-2026-0022 | cataract 55,000 vs 40,000 sub-limit, clause 7.1; 15,000 |
| Copay not applied | CLM-2026-0006 | handler proposed the full bill; 10 % copay 7,215.60 |
| Deductible not applied (UAE) | CLM-2026-0047 | AED 50 deductible missed; leakage AED 40 (copay applies after it) |
| Annual limit with history | CLM-2026-0014 | 275,000 of 300,000 already paid |
| Provider charges above peers | CLM-2026-0031 | prices 1.6–2.2× other hospitals; suspected |
| Related parties | CLM-2026-0007 | five members share one phone and bank account; suspected |
| Missing evidence | CLM-2026-0029 | itemised bill missing → clarification requested, amount 0 |

6. **Dashboard → Live score**: precision / recall against the hidden answer key of the synthetic set.
   *Say:* "We planted 64 leakage cases and 35 look-alikes; it finds the cases and leaves the look-alikes alone."

## One-line answers

- **Where is the AI?** It reads scanned bills into lines, links each policy rule to the clause in the policy
  wording (embeddings search), and investigates the suspected cases with tools. It never decides an amount.
- **Why rules for the money?** Every rupee must be explainable and repeatable for an auditor.
- **Real data?** No — two fictional insurers, synthetic members, hospitals and bills, generated from a fixed seed.
- **New insurer?** One product config (limits, lists, documents) plus its policy wording; no code change.
