# LeakLens — build plan (31 Oct 2026)

Challenge 08, Claims Leakage Detection Agent. Judging rewards **observable behaviour** on **synthetic data**, not slides.
Level 1 (gate, first 3 hours) → Level 2 unlocks after a mentor clears Level 1 → 18:00 code + prototype + deck locked.

## 1. What we are building

Upload claims (CSV / Excel / JSON) or scanned claim documents → every claim becomes one **master record**
(claim, invoice lines, policy terms, history, documents) → a **LangGraph workflow** runs the checks → each
finding carries an **amount (calculated vs suspected), the rule, the evidence and the policy clause** → a
**human reviews** (confirm / correct / dismiss / request clarification) → the **settlement is recalculated** →
dashboard, filters, audit log, and a **live score** against the hidden answer key.

```
 CSV/XLSX/JSON ─► INGEST + VALIDATE ─┐
                                     ├─► MASTER RECORD ─► LANGGRAPH: checks → assess → explain → [review gate] → settle
 documents ─► classify ─► [review] ─► digitise ─┘                      │
                                                                        ▼
                                            FastAPI ─► React console: Ingest · Claims · Claim detail · Dashboard · Config
```

### Level 1 must-haves (the brief, verbatim intent)
1. **Ingestion**: CSV / Excel / JSON + sample documents; validate ids, amounts, dates, mandatory fields; invalid rows are reported row by row, never silently dropped.
2. **Policy rule validation**: coverage status, exclusions, deductible, copay, sub-limits, overall benefit limit; each result names the rule and the outcome.
3. **Duplicates**: exact duplicate claim, duplicate line (within / across claims), near-duplicate (date / amount / reference differ slightly → review), legitimate repeat service (not flagged).
4. **Leakage assessment**: amount per finding; *calculated* (exact by rule, e.g. room 2,000 over the daily limit × 3 days = 6,000) kept separate from *suspected*; the calculation is shown.
5. **Dashboard**: claims processed, flagged, categories, amounts, severity; filters by claim type / provider / category / amount / date; an alert opens the claim with the rule and the supporting records.
Also: when evidence is missing, **ask for clarification instead of inventing a finding**.

### Level 2 (forecast)
Settlement recalculation vs the handler's proposed figure; history-aware benefit limits; provider peer benchmarking and related-party patterns; cross-document consistency; clarification workflow; case queue with aging; document path end-to-end; investigator agent with tools; live score.

## 2. Stack

| Layer | Choice |
|---|---|
| Workflow | LangGraph StateGraph, `interrupt()` human gates, SQLite checkpointer (a paused claim resumes later) |
| Models | Kimi K2.5 on AWS Bedrock (primary), Claude Sonnet on Bedrock (fallback), litellm; Titan Text Embeddings v2 for policy-clause retrieval |
| Extraction | versioned prompts + Pydantic schemas + json repair; extracted lines must reconcile to the printed total |
| Rules | pure Python (`core/checks`): every amount reproducible and explained |
| API | FastAPI + API key + audit log (`/docs`) |
| Data | MongoDB (GridFS for documents) or a local JSON store; pandas/openpyxl for files |
| UI | React 18 + Vite + TypeScript, antd 5, Tailwind 3, lucide-react |
| Ops | `cloudflared tunnel --url http://localhost:8000` for a public URL; docker-compose |

## 3. Contracts (do not change without telling D)

- `core/schemas/master.py` — Claim, InvoiceLine, Policy, HistoryRecord, ProductConfig, MasterRecord
- `core/schemas/finding.py` — Finding (check_id, category, severity, amount, amount_kind, rule, calculation, evidence, clause, status), CheckId list, ValidationIssue
- `core/schemas/settlement.py` — Settlement
- `core/checks/__init__.py` — `run_checks(record, history_index, other_claims=, peer_lines=)`, `recalculate_settlement(record, findings)`

## 4. API (backend)

| Endpoint | Purpose |
|---|---|
| `POST /ingest` (multipart) | any mix of .csv/.xlsx/.json/.pdf/.jpg/.png → `{batch_id, claims_created, validation:[{file,row,field,problem,accepted}]}` |
| `GET /claims?type=&provider=&category=&min_amount=&max_amount=&from=&to=&status=` | list rows: claim_id, claimant, provider, claim_type, requested_amount, currency, leakage_calculated, leakage_suspected, severity, status, updated_at |
| `GET /claims/{id}` | `{claim, policy, lines[], documents[], classification[], findings[], settlement, audit[], run}` |
| `POST /claims/{id}/run` · `GET /claims/{id}/run` | start / poll: `{status, steps:[{name,status,started,ended}], cost_usd}` |
| `POST /claims/{id}/classification/confirm` | body `[{page_id, document_type}]` (human gate 1) |
| `POST /claims/{id}/findings/{fid}/review` | body `{action: confirm|correct|dismiss|clarify, amount?, note}` → updated findings + settlement (human gate 2) |
| `GET /dashboard?…filters` | `{processed, flagged, leakage_calculated, leakage_suspected, awaiting_review, by_category[], by_severity[], by_provider[], by_check[]}` |
| `GET/PUT /config/{product}` | ProductConfig (currency, limits, copay, deductible, exclusions, non-payable list, required documents, auto-triage threshold) |
| `GET /documents/{id}` | file stream for the viewer |
| `GET /eval/summary` | precision / recall / amount recovered vs the answer key |
| `GET /audit?claim_id=` | audit rows |

Header `X-API-Key: <LEAKLENS_API_KEY>` on every call except `/health`.

`Finding` JSON: `{ finding_id, claim_id, check_id, category, severity: low|medium|high, amount, amount_kind: calculated|suspected, currency, rule_id, rule_text, calculation, reason, line_ids[], evidence:[{source, ref, quote}], clause?: {clause_id, text, score}, related_claim_ids[], status: open|auto_applied|confirmed|corrected|dismissed|clarification_requested, reviewer_note, corrected_amount? }`

## 5. UI brief (owner B)

Stack above. Primary colour `#2F7FF2`, font Outfit. `VITE_API_URL` (default `http://localhost:8000`), header `X-API-Key`. Start from mock JSON in `ui/src/mocks/` matching section 4; switch to live when the API is up.

1. **Ingest** — drag-and-drop for CSV/XLSX/JSON and documents; validation report table (file, row, field, problem, accepted); "N claims created".
2. **Claims** — table + filters (claim type, provider, leakage category, amount range, date range, status); columns per `GET /claims`.
3. **Claim detail** tabs — **Documents** (list + inline viewer), **Classification** (per page: thumbnail, predicted type, confidence, editable type, "Confirm classification"), **Master data** (lines: code, description, qty, unit price, amount, category, page; header totals; badge "lines = printed total ✓/✗"), **Findings** (one card each: check, severity, amount with a *Calculated* / *Suspected* badge, rule, calculation text, evidence quotes, policy clause + similarity; buttons Confirm / Correct (amount) / Dismiss / Request clarification; note), **Settlement** (requested → deductions by rule → deductible → copay → payable; proposed vs recalculated), **Audit**.
4. **Dashboard** — stat tiles (processed, flagged, leakage calculated / suspected, awaiting review), bars by category and severity, top providers; the same filters.
5. **Config** — per product JSON editor with Save.
6. **Live score** panel on the dashboard (`GET /eval/summary`).

## 6. Team

| Who | Owns | First | Then |
|---|---|---|---|
| A | `core/checks`, workflow nodes, document path | duplicates, policy rules, settlement, patterns on the synthetic data | document path, policy RAG, investigator agent |
| B | `ui/` | scaffold + Claims list + Claim detail (Findings) + Dashboard from mocks | Ingest, review actions, Documents viewer, Classification, Master data, Config, Live score |
| C | `data/synthetic`, `data/policies`, `eval/` | generator, planted leakage, answer key, exports | synthetic PDFs, policy wordings, eval numbers, deck |
| D | `backend/`, repo, submission | ingest + validation, store, endpoints, LangGraph skeleton | review/resume, dashboard, tunnel URL, docker-compose, submission |

Checkpoints: **13:30** Level 1 demo (ingest → findings → dashboard → review) · **16:30** Level 2 + documents end-to-end · **17:30** freeze · **17:40** submit.

## 7. Repo rules

- Synthetic data only; no real people, providers or insurers anywhere (data, fixtures, screenshots, commits).
- Secrets only in `.env` (gitignored). Never paste keys in code, logs, issues or chat.
- Commit every 30 minutes with real messages; D merges to `main` every hour; `main` must pass `pytest`.
- Small modules, type hints, keyword arguments, logging not print.
