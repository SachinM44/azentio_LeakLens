# Synthetic claims dataset

Everything under `data/synthetic/out/` is generated, fictional and deterministic. Two invented insurers in two
markets (an Indian retail health product in INR and a UAE group health product in AED), 8 providers, 60 members,
30 policies, 125 current claims with 5-40 invoice lines each, 40 earlier (paid) claims, planted leakage of every
kind in `core/schemas/finding.py::CheckId`, a hidden answer key, a documents manifest and rendered bills for eight
claims. No real person, hospital, insurer or claim appears anywhere.

## Regenerate

```
python -m data.synthetic.generate --out data/synthetic/out
```

Run from the repo root with the project venv. The seed is fixed (`SEED = 20261031`); two runs produce
byte-identical files (PDFs use reportlab's invariant mode, the workbook is re-zipped with pinned timestamps).
Every record is validated through the Pydantic models in `core/schemas/master.py` before it is written, and the
generator fails loudly on any invariant it cannot keep (line counts, key line ids, planted totals).

Code: `generate.py` (entities, one `plant_*` function per scenario, `finalise()` writes everything),
`catalog.py` (insurers, providers, names, service catalogues, diagnosis templates, clause ids),
`documents.py` (reportlab bill and discharge summary, JPEG rasteriser).

## Files and row counts

| File | What it is | Rows |
|---|---|---|
| `products.json` | 2 `ProductConfig` records: `IN-HEALTH-RETAIL` (INR), `AE-HEALTH-GROUP` (AED): required documents per claim type, non-payable lists, auto-triage threshold (5,000 / 500), near-duplicate window (3% / 3 days), repeatable codes, outlier z-score 2.5, policy wording file | 2 |
| `policies.json` | `Policy` records, nested sub-limits / exclusions / copay / deductible with clause ids | 30 (20 IN, 10 AE) |
| `providers.csv` | provider id, name, market, city, type, `in_network`, `profile` (normal / inflated / related-party), invoice prefix | 8 |
| `claimants.csv` | members with synthetic phone, bank account, address, policy | 60 |
| `claims.csv` / `claims.json` / `claims.xlsx` | `Claim` records; `invoice_numbers` pipe-joined in CSV; the workbook also carries sheets `invoice_lines`, `history`, `history_lines`, `providers`, `claimants` | 125 |
| `invoice_lines.csv` / `.json` | `InvoiceLine` records plus one extra column `patient_share` (AED member share; 0 for INR) | 1,992 |
| `history.csv` / `history.json` | `HistoryRecord` records paid 2025-06..2026-02; `history.json` nests the lines | 40 (15 with lines) |
| `history_lines.csv` | the nested history lines, flat | 137 |
| `answer_key.json` | `positives` / `negatives` (see below), counts per check, conventions | 64 / 35 |
| `documents_manifest.json` | per claim: required document types, which are present, which are missing, `document_facts` as printed on the bill, file paths for rendered documents | 125 |
| `documents/<claim_id>/` | rendered itemised bill + discharge summary for 8 claims; `CLM-2026-0054` is a 150-dpi JPEG scan rotated 1.5 degrees (per page) instead of a PDF | 8 claims |
| `../../policies/IN-HEALTH-RETAIL.md`, `AE-HEALTH-GROUP.md` | policy wordings, numbered clauses; the clause ids on sub-limits and exclusions in `policies.json` point into them | ~45 clauses each |

Ids: claims `CLM-2026-0001..0125` (numbered by submission time), members `M-0001..0060`, policies
`POL-IN-0001..0020` / `POL-AE-0001..0010`, providers `P-001..P-008`, history `HCL-2025-0001..0040`, invoices
`<prefix>-<year>-<n>`, lines `<claim_id>:<invoice_no>:<serial_no>`, documents `DOC-<claim_id>-<n>`.

## The two rule books in one paragraph each

**IN-HEALTH-RETAIL** (Sahara Health Assurance): sum insured 300,000-1,000,000; room rent limit 1% of SI per day,
ICU 2%; 10% copay on half the policies (all claim types); deductible 0; sub-limits cataract 40,000 per claim,
maternity 50,000 per delivery, physiotherapy 20 sessions a year; exclusions cosmetic, dental, OPD; 25 non-payable
consumables; 30-day waiting period; 730-day PED waiting period with `diabetes` / `hypertension` declared on six
policies; `proportionate_deduction` true. Policy 19 ends 2026-03-31, policy 20 starts 2026-02-15.

**AE-HEALTH-GROUP** (Gulf Shield Takaful): annual limit 150,000 AED; deductible 50 per out-patient visit, then 20%
copay out-patient, 30% pharmacy, 0% in-patient; exclusions dental, optical, cosmetic; 12 non-payables; policies 1-7
restrict the network to P-004 and P-005 (P-006 is out of network), policies 8-10 have an empty network list.
Lines carry CPT / CDT / drug / service codes and a `patient_share`.

Providers: P-001..P-003 (IN) and P-004..P-006 (AE) price at 0.92-1.08x (IN) / 0.95-1.05x (AE) of the catalogue;
**P-007** prices every code at 1.6-2.2x; **P-008** is where the related-party ring claims.

## Conventions the checks should follow (they are what the key assumes)

- **Stay** = `discharge_date - admission_date` in days (nights); same-day discharge counts as 1. Room + ICU days
  add up to the stay on clean claims.
- **Handler's settlement** (`proposed_settlement`) = `(lines total - deductible) x (1 - copay%)`, deductible only
  per out-patient visit (AE), copay by claim type (day care uses the in-patient rate). On planted claims the
  handler figure *includes* the leaked lines (that is the leakage); on `COPAY_NOT_APPLIED` it equals the full
  total, on `DEDUCTIBLE_NOT_APPLIED` it is 80% of the total (so the leak is 50 x 80% = 40), on
  `SETTLEMENT_MISMATCH` it is above the recalculation for a reason no other check explains.
- **ROOM_LIMIT_EXCEEDED** amount = `(rate - daily limit) x days` for the room or ICU line only; proportionate
  deduction is described in clause 3.3 but is not part of the key amount.
- **NON_PAYABLE_ITEM** and **EXCLUDED_SERVICE** = one key row per claim, the sum of those lines. Non-payable line
  descriptions start with the list entry ("Surgical gloves (pair)"); payable medical items (cannula, infusion
  set, dressing pack, sutures, prescribed vitamins) never match an entry.
- **SUBLIMIT_EXCEEDED** amount = claim total - sub-limit (all lines of the claim belong to the package).
- **BENEFIT_LIMIT_EXCEEDED** = `requested - (annual_limit - sum of history paid_amount on the same policy)`.
- **DUPLICATE_CLAIM / NEAR_DUPLICATE**: the *later* submission is the positive; the original is a key negative.
  Near-duplicates are +1 day, +2% on every line, new invoice number; the product tolerance is 3% / 3 days.
- **CROSS_CLAIM_DUPLICATE_LINE**: a readmission on the day the earlier (history) episode ended; the re-billed CT
  line has the same code, date and amount as a paid history line, and sits inside the new episode.
- **PROVIDER_PRICE_OUTLIER**: compute peer statistics *leaving the provider under test out* (or against the peer
  median). With P-007 inside a five-provider population the z-score never reaches 2.5. Key amount (suspected) =
  sum of (unit price - catalogue base) x qty.
- **RELATED_PARTY_PATTERN**: phone + bank account + address shared across claimants on *different* policies.
  Spouses on one policy share only the address (key negatives).
- **CONSISTENCY_MISMATCH / MISSING_EVIDENCE** read `documents_manifest.json`: `document_facts` carries the name /
  policy number / dates / invoice / net payable as printed on the bill (the two mismatch cases print another
  member's name or policy number), `required_documents_present` and `missing_documents` list the types.
  `MISSING_EVIDENCE` has amount 0: request the document, do not invent a finding.
- Suspected amounts are exposure (the claim total), not leakage, and are not scored for exactness.

## Planted cases (answer key)

| check_id | kind | claims (amount) |
|---|---|---|
| DUPLICATE_CLAIM | calculated | CLM-2026-0079 (24,168), CLM-2026-0100 (15,228) |
| DUPLICATE_LINE | calculated | CLM-2026-0067 (840), CLM-2026-0103 (95 AED), CLM-2026-0124 (440) |
| CROSS_CLAIM_DUPLICATE_LINE | calculated | CLM-2026-0013 (6,370), CLM-2026-0113 (7,020) |
| NEAR_DUPLICATE | suspected | CLM-2026-0009, CLM-2026-0030, CLM-2026-0069 (one against history) |
| ROOM_LIMIT_EXCEEDED | calculated | **CLM-2026-0033 (6,000: the brief's 5,000 vs 3,000 x 3 days)**, CLM-2026-0045 (1,600), CLM-2026-0060 (4,000 ICU), CLM-2026-0114 (8,000) |
| EXCLUDED_SERVICE | calculated | CLM-2026-0016 (6,650 dental), CLM-2026-0075 (19,180 cosmetic), CLM-2026-0121 (495 AED dental) |
| NON_PAYABLE_ITEM | calculated | 10 claims: 0007, 0016, 0031, 0033, 0045, 0055, 0060, 0091, 0101 (AED), 0114 |
| SUBLIMIT_EXCEEDED | calculated | CLM-2026-0022 (15,000: cataract 55,000 vs 40,000), CLM-2026-0043 (30,000: maternity 80,000 vs 50,000) |
| BENEFIT_LIMIT_EXCEEDED | calculated | CLM-2026-0014 (78,127), CLM-2026-0096 (87,708) |
| COPAY_NOT_APPLIED | calculated | CLM-2026-0006 (7,215.60), CLM-2026-0072 (3,001.80), CLM-2026-0073 (2,868.10) |
| DEDUCTIBLE_NOT_APPLIED | calculated | CLM-2026-0047, CLM-2026-0053, CLM-2026-0074 (40 AED each) |
| SETTLEMENT_MISMATCH | calculated | CLM-2026-0048 (5,000: gross paid over a discount line), CLM-2026-0097 (400 AED) |
| QUANTITY_VS_STAY | calculated | CLM-2026-0039 (13,380), CLM-2026-0117 (5,040) |
| DATE_OUTSIDE_EPISODE | calculated | CLM-2026-0039 (970), CLM-2026-0117 (850) |
| ARITHMETIC_MISMATCH | calculated | CLM-2026-0038 (1,000), CLM-2026-0083 (800) |
| COVERAGE_INACTIVE | calculated | CLM-2026-0080 (22,648) |
| WAITING_PERIOD | calculated | CLM-2026-0019 (52,460: declared PED), CLM-2026-0041 (13,949: 18 days into the policy) |
| OUT_OF_NETWORK | calculated | CLM-2026-0115 (20,616 AED), CLM-2026-0116 (18,444 AED) |
| PROVIDER_PRICE_OUTLIER | suspected | CLM-2026-0031, 0055, 0083, 0098 (all P-007) |
| RELATED_PARTY_PATTERN | suspected | CLM-2026-0007, 0029, 0042, 0057, 0067 (all P-008) |
| CONSISTENCY_MISMATCH | suspected | CLM-2026-0037 (another member's name), CLM-2026-0054 (another policy number) |
| MISSING_EVIDENCE | suspected, 0 | CLM-2026-0029, CLM-2026-0042, CLM-2026-0046 |

64 positives on 50 claims; 75 of 125 claims (60%) are clean. Several claims carry more than one planted case
(non-payables on the room-limit, P-007 and P-008 claims; a duplicate line and two missing documents on P-008
claims; a late line on each quantity-vs-stay claim).

35 negatives cover the look-alikes that must not fire: 6 physiotherapy sessions on distinct dates (two members), 3
dialysis sessions, CBC on two dates, the originals of the duplicate and near-duplicate pairs, a room rate exactly
on the limit, spouses at the same hospital, P-006 under open-network policies, payable consumables, a prescribed
vitamin, a cataract inside the sub-limit, a member with history well below the limit, unrelated diagnoses on PED
policies, and "do not double count" `SETTLEMENT_MISMATCH` rows on the copay / deductible / quantity cases.

Rendered documents: CLM-2026-0022 (cataract sub-limit), 0032 (clean, AED), 0033 (the room example + non-payables),
0037 and 0054 (consistency mismatches; 0054 is the JPEG scan), 0038 (arithmetic), 0059 (clean), 0124 (duplicate
line). Those eight claims have `source = "mixed"`; all other claims are `structured` and their manifest entries
list document types and facts without files.

## Scoring

```
python -m eval.run --findings <findings.json> --key data/synthetic/out/answer_key.json [--strict]
```

Prints precision / recall per check and overall, the calculated amount recovered against the key, amount drift on
matched calculated cases, findings outside the key, and every key negative that was flagged. Exit code 1 when any
planted calculated case is missed (with `--strict`, also on amount drift or a flagged negative).
