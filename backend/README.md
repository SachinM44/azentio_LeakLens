# LeakLens backend

FastAPI service over the master dataset: ingest structured files and documents, validate every row, run the
leakage checks through a checkpointed LangGraph workflow with two human gates, recalculate the settlement,
and expose the dashboard, config, audit and evaluation endpoints the UI uses.

## Run

```bash
# from the repo root, inside the .venv (Python 3.11)
.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000
# Swagger UI:  http://localhost:8000/docs
```

Tests: `.venv/Scripts/python.exe -m pytest tests/test_backend.py -q`

Graph diagram (Mermaid text to `docs/graph.mmd`): `.venv/Scripts/python.exe -m backend.graph_diagram`

## Environment (`.env`, loaded by pydantic-settings; never committed)

| Variable | Default | Meaning |
|---|---|---|
| `LEAKLENS_API_KEY` | `change-me` | Value of the `X-API-Key` header; every endpoint except `GET /health` requires it |
| `MONGODB_URI` | unset | When set, the MongoDB store (pymongo + GridFS for document bytes) is used |
| `MONGODB_DB` | `leaklens` | Database name for the MongoDB store |
| `DATA_DIR` | `data/store` | Root of the local JSON store and the SQLite checkpointer |
| `COST_CAP_USD_PER_CLAIM` | `2` | Spend cap per claim for the document models (`CostMeter`); shown on each run as `cost_cap_usd` |
| `POLICIES_DIR` | `data/policies` | Policy wording per product (`<product_id>.md`, numbered clauses) for clause retrieval |
| `DOCUMENTS_OFFLINE` | `false` | Document models answer from the per-claim cache only (tests, demos without network) |
| `INVESTIGATOR_ENABLED` | `true` | Run the investigator agent over suspected findings (`0` to skip it) |
| `AWS_*` | - | Model access, read by `core/llm` (not by the backend itself) |

## Store

`backend/store.py` defines one `Repository` interface (`upsert`, `get`, `list(filter)`, `delete`,
`save_document`, `open_document`) with two implementations picked at startup:

- **JSON files** (default, nothing to install): `DATA_DIR/<collection>.json` per collection, document bytes under
  `DATA_DIR/documents/`.
- **MongoDB** when `MONGODB_URI` is set: one collection per entity, documents in GridFS.

Collections: `products`, `policies`, `claims`, `invoice_lines`, `history`, `documents`, `master_records`, `findings`,
`settlements`, `reviews`, `audit`, `runs`, `batches` (plus `providers` / `claimants` when such files are ingested).

Product configs are also seeded from `data/config/products/*.json` at startup when not already stored.

## Workflow (LangGraph, `backend/graph.py`)

```
load_record -> [classification_gate] -> run_checks -> assess -> investigate -> settle -> [review_gate -> settle ...] -> done
```

- `load_record` rebuilds the `MasterRecord` (claim + lines + policy + product + history of the same member /
  policy + documents, document types and document facts).
- `classification_gate` runs only when the claim has documents whose type is not yet confirmed; it calls
  `interrupt()` and resumes on `POST /claims/{id}/classification/confirm`.
- `run_checks` calls `core.checks.run_checks(record, history_index, other_claims=..., peer_lines=...)`.
- `assess` auto-applies calculated findings at or under the product's `auto_triage_threshold`; the rest stay open.
- `investigate` runs only when the claim has suspected findings: the investigator agent
  (`core/agent/investigator.py`, read-only tools over the record, history, peer prices and clauses) leaves a
  `recommendation`, `recommendation_confidence` and `recommendation_note` on each suspected finding; its tool trail,
  model and token counts are stored on the run as `investigation`, and its tokens are priced into `cost_usd`
  ($0.72 / $3.60 per million input / output). It never changes a status or an amount, and a failure is logged
  and skipped (`INVESTIGATOR_ENABLED=0` turns it off).
- `settle` calls `core.checks.recalculate_settlement` on the stored findings (reviews land there).
- `review_gate` calls `interrupt()` while any finding is open; each `POST .../findings/{fid}/review` resumes it,
  `settle` runs again with the reviewed findings, and the loop ends when nothing is open.
- After `run_checks`, policy-rule findings get their governing clause from the product's wording
  (`core/rag/policy_index.py`: `POLICIES_DIR/<product_id>.md`, embeddings with a BM25 fallback); the index mode is
  returned as `retrieval_mode` on the run (`null` when the product has no wording file).
- Checkpoints live in `DATA_DIR/checkpoints.sqlite` (`SqliteSaver`, `thread_id = claim_id`), so a paused claim
  survives a restart. Progress per node is written to the `runs` collection, which `GET /claims/{id}/run` returns.

## Document path (`backend/documents.py`)

1. `POST /ingest` stores PDFs / images and attaches each to the claim whose id prefixes its file name; every page
   gets a file-name guess (`predicted_by: filename`).
2. `POST /claims/{id}/documents/classify` renders the pages and asks the page classifier
   (`core/documents/pipeline.classify_pages`); predictions replace the guesses (`predicted_by: model`).
3. The reviewer confirms the types: `POST /claims/{id}/classification/confirm`. The backend then digitises the
   documents (`digitise_documents`): when the claim has no structured lines the digitised lines become the master
   lines and `claim.source = "documents"`; when structured lines exist they stay and the digitised lines are kept
   under `master_records.document_lines` for the Master data tab. Document facts, the printed total and the
   reconciliation flag always go to the master record (collection `digitisations`). The workflow then continues
   to `run_checks` (resuming the paused thread, or starting a run when none was paused).
4. Model spend is metered per claim (`COST_CAP_USD_PER_CLAIM`) and added to the claim (`document_cost_usd`) and to
   its latest run (`cost_usd`). The per-claim model cache lives in `DATA_DIR/cache/<claim_id>/` (gitignored).

A model failure never blocks the claim: classify keeps the file-name guesses and reports `error`; confirm stores
the types, records `digitisation_error` on the claim and continues with the structured lines.

### Synthetic documents manifest

When `data/synthetic/out/documents_manifest.json` exists (`DOCUMENTS_MANIFEST_PATH`), ingesting the synthetic
claims uses it: every document the manifest lists for a claim goes into the master record (`documents` =
document ids, `document_types` = id -> type, `document_facts` = the header facts with nulls dropped), rendered
files under `documents_root` are stored and attached to the claim at ingest, and `printed_total` / `reconciled`
come from `net_payable`. A type confirmed through the review console wins over the manifest's.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | public |
| POST | `/ingest` | multipart `files[]`: csv / xlsx / json / pdf / jpg / png |
| GET | `/claims` | filters `type, provider, category, min_amount, max_amount, from, to, status` |
| GET | `/claims/{id}` | claim, policy, product, lines, documents, classification, findings, settlement, audit, run, summary |
| POST | `/claims/{id}/run` | starts a run in the background, returns `{run_id}` |
| GET | `/claims/{id}/run` | `{status, steps[], cost_usd, paused_at}` |
| POST | `/claims/{id}/documents/classify` | model page classification over the claim's documents; predictions land in `classification[]` |
| POST | `/claims/{id}/classification/confirm` | body `[{page_id, document_type}]`; stores the confirmed types, digitises, continues the workflow |
| POST | `/claims/{id}/findings/{fid}/review` | body `{action: confirm/correct/dismiss/clarify, amount?, note}` |
| GET | `/dashboard` | same filters; counts, amounts, by_category / by_severity / by_provider / by_check |
| GET, PUT | `/config/{product}` | `ProductConfig`; `GET /config` lists all |
| GET | `/documents/{id}` | streams the stored file with its mime type |
| GET | `/eval/summary` | precision / recall / amount recovered vs `data/synthetic/out/answer_key.json` |
| GET | `/audit?claim_id=` | newest first |

Every mutating endpoint writes an audit row `{ts, actor, action, claim_id, details}`.

Ingest never drops a row silently: rows with errors are reported in `validation[]` with `accepted=false` and not
stored; rows with warnings (unknown policy, negative line amount, orphan line) are stored and reported with
`accepted=true`. A document whose file name starts with a claim id (`CLM-2026-0007_bill.pdf`) is attached to
that claim; any other document is stored and reported as unattached.

## Walk-through with curl

Use the synthetic set in `data/synthetic/out/` when it exists; the commands below use the small fixture in
`backend/fixtures/` (3 claims, 2 policies, 20 lines, 3 history rows, 2 products, 1 synthetic bill PDF, and one
file with a deliberately broken row).

```bash
export KEY=leaklens-dev   # the value of LEAKLENS_API_KEY in .env

curl -s localhost:8000/health

# 1. ingest (any mix of files in one call)
curl -s -H "X-API-Key: $KEY" -X POST localhost:8000/ingest \
  -F files=@backend/fixtures/products.json -F files=@backend/fixtures/policies.json \
  -F files=@backend/fixtures/claims.csv -F files=@backend/fixtures/invoice_lines.csv \
  -F files=@backend/fixtures/history.csv -F files=@backend/fixtures/CLM-2026-0001_bill.pdf \
  -F files=@backend/fixtures/broken_claims.csv | python -m json.tool
# -> counts per entity, claims_created, and validation[] naming broken_claims.csv row 3 (accepted=false)

# 2. list and detail
curl -s -H "X-API-Key: $KEY" "localhost:8000/claims?type=inpatient&min_amount=50000"
curl -s -H "X-API-Key: $KEY" localhost:8000/claims/CLM-2026-0001 | python -m json.tool

# 3. run a claim and poll its progress
curl -s -H "X-API-Key: $KEY" -X POST localhost:8000/claims/CLM-2026-0001/run
curl -s -H "X-API-Key: $KEY" localhost:8000/claims/CLM-2026-0001/run
# CLM-2026-0001 has a PDF, so the run pauses at classification_gate; confirm the page types:
curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -X POST localhost:8000/claims/CLM-2026-0001/classification/confirm \
  -d '[{"page_id":"<document_id>:1","document_type":"itemized_final_hospital_bill"},
       {"page_id":"<document_id>:2","document_type":"discharge_summary"}]'
# (page ids come from the detail's classification[]; the run then continues to run_checks -> assess -> settle)

# 4. review a finding (the run pauses at review_gate while any finding is open)
curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -X POST localhost:8000/claims/CLM-2026-0001/findings/<finding_id>/review \
  -d '{"action":"correct","amount":4000,"note":"two days over the limit, not three"}'
# -> the claim's findings and the recalculated settlement

# 5. dashboard, config, audit, evaluation
curl -s -H "X-API-Key: $KEY" "localhost:8000/dashboard?provider=PRV-IN-01"
curl -s -H "X-API-Key: $KEY" localhost:8000/config/IN-HEALTH-RETAIL
curl -s -H "X-API-Key: $KEY" "localhost:8000/audit?claim_id=CLM-2026-0001"
curl -s -H "X-API-Key: $KEY" localhost:8000/eval/summary

# 6. view a document
curl -s -H "X-API-Key: $KEY" -o bill.pdf localhost:8000/documents/<document_id>
```

## Module map

| File | Role |
|---|---|
| `settings.py` | env / `.env` settings |
| `auth.py` | `X-API-Key` dependency |
| `store.py` | repository interface, JSON-file and MongoDB implementations |
| `ingest.py` | file parsing, entity detection, row validation, documents, master-record refresh |
| `master.py` | `MasterRecord` builder, history index, other claims, peer lines, documents manifest |
| `graph.py` | the LangGraph workflow, checkpointing, run progress, start / resume |
| `views.py` | list rows, filters, claim detail, dashboard aggregates, audit writer |
| `api.py` | the routes |
| `eval_summary.py` | findings vs the hidden answer key |
| `graph_diagram.py` | writes `docs/graph.mmd` |
| `main.py` | app factory, CORS, startup seeding |
