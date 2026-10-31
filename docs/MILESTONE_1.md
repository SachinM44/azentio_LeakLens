# Milestone 1 — Validate claims and detect potential leakage

What the brief asks, what LeakLens does, and how to see it in two minutes.

| # | Required capability | How LeakLens meets it | Where to look |
|---|---|---|---|
| 1 | Ingest claims, invoice lines, policies, history (CSV / Excel / JSON) and sample documents; validate ids, amounts, dates, mandatory fields; never drop invalid rows silently | `POST /ingest` accepts any mix of files, detects each table, validates every row and returns a row-level report (`file, row, field, problem, accepted`). Rows with errors are reported and not stored; warnings are stored and reported. Documents are attached to their claim by id. | Ingest screen · `scripts/demo_level1.py` step 2 |
| 2 | Policy rule validation: coverage, exclusions, deductibles, copay, sub-limits, benefit limits; each result names the rule and the outcome | 22 checks in `core/checks`. Every finding carries `rule_id`, `rule_text`, the `calculation`, the evidence rows and, for policy rules, the governing clause of the policy wording with a retrieval similarity score. | Claim detail → Findings |
| 3 | Duplicates: exact duplicate claim, duplicate line within / across claims, near-duplicate for review, legitimate repeat service not flagged | `DUPLICATE_CLAIM`, `DUPLICATE_LINE`, `CROSS_CLAIM_DUPLICATE_LINE` (calculated) and `NEAR_DUPLICATE` (suspected); repeat services on other dates are left alone (35 planted look-alikes → 0 flags). | Findings; `GET /eval/summary` |
| 4 | Leakage amount per issue; calculated discrepancy kept apart from estimated / suspected; the calculation explained | `amount_kind` is `calculated` or `suspected` on every finding and the dashboard totals keep them separate. Example in the set: room 5,000/day vs limit 3,000 × 3 days = 6,000 calculated (CLM-2026-0033). | Findings card, Dashboard tiles |
| 5 | Dashboard: processed, flagged, categories, amounts, severity; filters by claim type, provider, category, amount, date; alert → claim, rule, supporting records | `GET /dashboard` and `GET /claims` take the same filters; opening an alert shows the claim, its lines, the rule and the evidence. | Dashboard, Claims list |
| + | Request clarification rather than inventing a finding | `MISSING_EVIDENCE` findings with amount 0 and the list of absent documents / fields. | Findings |
| + | Human review | confirm / correct / dismiss / request clarification; the settlement is recalculated and an audit row is written; the workflow pauses at the review gate and resumes on the action. | Claim detail → Findings, Settlement, Audit |
| + | Self-check | `GET /eval/summary`: precision / recall / amount recovered against the hidden answer key of the synthetic set. | Dashboard → Live score |

## Two-minute walkthrough

1. Start the API: `uvicorn backend.main:app --port 8000` (store: local JSON, or MongoDB when `MONGODB_URI` is set).
2. `python -m scripts.demo_level1` — ingests the synthetic set (125 claims, 1,992 lines, 30 policies, 40 history rows), runs every claim, prints the dashboard, opens CLM-2026-0033, dismisses one finding (money moves back, audit row), prints the eval score.
3. In the UI: Ingest → Claims (filters) → CLM-2026-0033 → Findings (calculated vs suspected, rule, calculation, clause) → Settlement (proposed vs recalculated) → Dashboard → Live score.

## Numbers on the synthetic set (31 Oct)

- Ingest 125 claims in about 2 s; 2 validation warnings (negative discount lines kept and reported), 0 silent drops.
- All 125 runs finish in about 50 s; 36 claims wait for a human at the review gate.
- Eval against the answer key: precision 1.00, recall 0.98; calculated leakage found 496,509.50 = the planted total.
- Data is synthetic: two fictional insurers (India, INR; UAE, AED), fictional providers and members.
