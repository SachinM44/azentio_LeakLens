LeakLens — final plan for build day (31 Oct 2026, written ~11:15, clock running)
This file is the "one final md" you asked for: my take on every point you raised, the architecture diagram, what we build per milestone, the team split against the clock, and a brief for your UI teammate that never mentions where our code comes from. After you approve, I copy it to hackathon/prep/FINAL_PLAN.md (outside the shared repo) and start executing.

0. What changed this morning (read this first)
The Level 1 brief (Downloads/azentio_ai_hackathon_challenges_level1.docx, Claims Leakage section) changes three things:

Synthetic or anonymised data only — it is a rule, not a preference. Real claims are out of the demo and out of the repo. (Our real 6-page claim stays as a private smoke test on your laptop only.)
Level 1 is structured-data first. Required: ingest CSV / Excel / JSON (claim records, invoice lines, policy details, claim history + settlements) plus sample document uploads; validate ids/amounts/dates/mandatory fields and never drop invalid rows silently; policy rules (coverage, exclusions, deductible, copay, sub-limits, benefit limit); duplicates (exact claim, duplicate line within/across claims, near-duplicate → review, legitimate repeat → not flagged); leakage amount per finding, calculated vs suspected clearly separated, with the calculation shown; a dashboard (counts, categories, amounts, severity; filters by claim type / provider / category / amount / date; alert → claim + rule + records). "Request clarification instead of inventing a finding" when evidence is missing.
Milestones gate each other. 11:00 start → Level 1 "suggested 0–3 h" → the next brief unlocks only after a mentor clears the current one → 18:00 code + prototype + deck locked on HackCulture → 18:30 Top 10 → 18:45 final jury. Judging is "observable behaviour, not architecture slides or unsupported AI claims".
So: our document pipeline (classify → review → digitise → master data) is the differentiator, but the gate is the structured path. We build the structured path to Level 1 first, and the document path lands on top of the same master dataset.

1. Your points, one by one (my take)
#	Your point	My take
1	"Only FastAPI, no AI framework, no RAG — how is that a hiring-grade build?"	You're right that the first plan under-sold it. FastAPI is only the HTTP layer. The AI stack is: LangGraph workflow (nodes = ingest → validate → master → checks → assess → explain → human review, with interrupt() human gates and a checkpointer so a paused claim resumes later), Kimi K2.5 and Claude Sonnet on Bedrock via litellm (same account; I checked: ap-south-1 has both plus Titan/Cohere embeddings), a real RAG over policy wording (clauses → Titan embeddings → vector search → the model cites the governing clause), a tool-calling investigator agent for the "suspicious pattern" scenarios (tools = rule engines, history lookup, clause lookup, provider peer stats), and schema-validated vision extraction for documents. That is a full agentic design a Forward Deployed Engineer panel recognises, and every piece is observable on screen.
2	"Why FHIR/ICMR? Our flow is classification → review console → digitisation → master dataset → modules"	FHIR/ICMR were only listed as cut; they are not built. The build follows exactly your flow: upload → page classification → classification review console (human gate 1) → digitisation → master dataset → every check runs on the master dataset → findings review console (human gate 2) → settlement. Structured files (CSV/JSON) feed the same master dataset directly, so one engine serves both inputs.
3	Synthetic data only	Agreed and now mandatory. Teammate C generates it (section 4): two insurers in two markets, planted leakage of every scenario, with a hidden answer key so we can show a live precision/recall score.
3b	UI to your teammate, no trace of our origin	Section 6 is a self-contained brief with the API contract and screens. It names nothing from our company.
3c	"If everything is deterministic, what's the AI for?"	AI does what rules cannot: reads bills/discharge summaries into structured lines; turns policy wording into rules and cites the clause; decides whether "CBC" and "Complete Blood Count" are the same test (duplicate vs legitimate repeat); judges whether a repeated physio session is plausible; writes the explanation and the clarification request; and the investigator agent chooses which tools to run for an unusual claim. Rules only do the arithmetic, which is what makes the money auditable. The line for the judges: "AI finds and explains, rules compute, humans decide."
3d	"How are the required documents per insurer configured?"	A per-product config (config/products/*.json) holds the required-document checklist (IP health: claim form, itemised bill, discharge summary, reports, prescriptions, KYC, pre-auth; OP: invoice + prescription; motor: FIR, estimate, invoice, photos, RC, DL), limits, copay, deductible, exclusions, the non-payable list, currency and auto-triage thresholds. The Config screen edits it. Missing documents become a "clarification requested" finding (scenario 5), never an invented one.
4	"Why not Vertex RAG on a new account?"	Setup (project, billing, Discovery Engine data store, indexing, service account) is 1–2 hours of risk on a 7-hour clock and the judges score behaviour, not vendor names. We get the same hiring signal with a local vector RAG: policy clauses → Titan Text Embeddings v2 on Bedrock → cosine search → model cites the clause with a similarity score on screen. Same index also matches rate-card names (synonyms).
4b	"Store documents in a DB so we can show View Document"	Yes: MongoDB Atlas free tier (M0, cloud, 5-minute setup by C, no RAM on your laptop) with GridFS for uploaded documents; GET /documents/{id} streams the file to a viewer in the UI. Collections: policies, claims, invoice_lines, histories, documents, master_records, findings, reviews, audit, runs, configs. If Atlas fails on venue Wi-Fi, D switches the repository class to local JSON files (same six methods). No S3 and no company buckets.
5	"Show digitised data like our console; classification review; fastest storage"	Claim page tabs: Documents (viewer) · Classification (page-type table, edit, confirm — gate 1) · Master data (lines with code/qty/rate/amount/category/page, header totals, reconciliation status) · Findings · Settlement · Audit. Storage answer as above.
7	"Where is the IRDAI list configured? Review can't be purely manual"	Config screen per product (non-payable list, limits…). Review is a queue with auto-triage: a finding whose amount is calculated and whose rule is certain (exact duplicate, limit arithmetic) is auto-applied when under a configurable threshold and still reviewable later; suspected findings (near-duplicate, provider outlier, pattern) always wait for a human. Every action (confirm / correct / dismiss / request clarification) is an audit row, the graph resumes from the checkpoint, and a case can be reopened.
7b	"Progress, and which env?"	runs collection with per-step status + timestamps; UI polls GET /claims/{id}/run. Backend runs on your laptop (uvicorn), UI on the teammate's laptop (Vite) or served by the backend as static files, DB on Atlas. For the judges and the 18:00 submission we expose a public URL with cloudflared tunnel --url http://localhost:8000 (one command, no account).
8	Can't mention our product; classification human-in-the-loop as guardrail 1	Exactly: gate 1 = confirm page types before digitisation; gate 2 = findings review before settlement. Plus schema validation, totals reconciliation, clause citation, cost cap, audit log, injection-safe prompts (section 2.3).
9	Architecture diagram	Section 2.
10	Fraud: wrong claim sheet submitted for the wrong claim	Not photo-ID. We add CONSISTENCY_MISMATCH: claimant name, policy number, dates, provider and invoice numbers must agree across the claim record, invoice, discharge summary and policy; a disagreement = "document may belong to another claim" → review with the two conflicting values quoted. And RELATED_PARTY_PATTERN: shared phone / bank account / address across claimants at one provider → pattern for review (scenario 4), never an automatic fraud verdict.
9b	Use the Aditya Birla claim for PED/exclusions	The claim cannot be used (synthetic-only rule). The policy wording is a public document: if you have the PDF, drop it in data/policies/ and it becomes the Indian product's clause source for the RAG; otherwise C authors the clauses. PED/exclusion then moves money (₹ excluded line → 0, clause cited) instead of a flag only.
10b	Storage counts for tech	MongoDB Atlas + GridFS as above.
11	Drop the Gemini fallback	Dropped. Fallback = Claude Sonnet 5.5 on the same Bedrock key (no extra setup). Kimi K2.5 primary.
11b	Middle East, Premia customers, out of the box	Azentio's own customer wall lists Star Health and Liberty (India) and GCC names: Emirates Insurance (2026 case study), Al Wathba, Abu Dhabi National Takaful, Al Fujairah National, Takaful Oman, AICC (Saudi), Qatar Islamic Insurance. So the synthetic data has two insurers: an Indian retail health insurer (INR; room-rent limit, copay, IRDAI non-payables, PED) and a UAE group health insurer (AED; DHA eClaimLink vocabulary — Encounter/Activity, CPT codes, network tiers, patient share, deductible per visit, annual limit) — same engine, two currencies, two rule books. A motor claim set (garage invoice: parts vs labour, depreciation, deductible) is the Level 2/3 stretch and matches Azentio's Claim Automation.
12	Share code with the panel, no trace	The shared repo is a fresh leaklens repo: core/ (our kit, every header rewritten, no company or product names anywhere; prompt files keep version: and sha: only), backend/, ui/, data/synthetic/, eval/. The prep docs stay outside the repo. A grep gate runs before sharing. One honest line stays in the README: "Prompt templates and rule helpers were adapted from the team's prior work, with permission." It names nothing and keeps us inside the "declare reused libraries" rule if a judge asks "did you write all of this today?". Also "the plain one": we ship only the functions we call (about 10 bill helpers, not 900 lines).
13	Judge hints from the briefing	Mapped in section 8.
2. Architecture
2.1 Diagram
                 ┌────────────────────────────── INPUTS (synthetic) ──────────────────────────────┐
                 │  CSV / XLSX / JSON: claims, invoice lines, policies, history+settlements        │
                 │  Documents: bill PDF, discharge summary, claim form, invoice images              │
                 └───────────────┬─────────────────────────────────────────┬───────────────────────┘
                                 │ structured                               │ documents
                                 ▼                                          ▼
                 ┌──────────────────────────┐              ┌─────────────────────────────────────┐
                 │ INGEST + VALIDATE         │              │ PAGE CLASSIFIER (Kimi, vision)       │
                 │ pandas/openpyxl; schema   │              │ → CLASSIFICATION REVIEW  [human gate 1]│
                 │ checks; invalid rows kept │              │ → DIGITISE bill + header (schema)    │
                 │ and reported, never dropped│             │ → RECONCILE lines to printed total   │
                 └───────────────┬──────────┘              └───────────────────┬─────────────────┘
                                 └───────────────────┬──────────────────────────┘
                                                     ▼
                                   ┌──────────────────────────────────┐
                                   │ MASTER DATASET (MongoDB)          │
                                   │ claim · lines · policy terms ·    │
                                   │ history · documents(GridFS)       │
                                   └───────────────┬──────────────────┘
                                                   ▼
   ┌───────────────────────────── LANGGRAPH WORKFLOW (checkpointed, resumable) ──────────────────────────────┐
   │  policy_rules ─┐                                                                                          │
   │  duplicates ───┤   each check = pure rule function → Finding(amount: calculated | suspected, rule, evidence)│
   │  settlement ───┼──► leakage_assess ──► explain (model writes reason + clarification requests)              │
   │  consistency ──┤                      ▲                                                                   │
   │  provider_stats┘                      │ POLICY RAG: clauses → Titan embeddings → top-k → clause cited      │
   │                                       │ INVESTIGATOR AGENT (tool calls): history, peers, clauses, lines   │
   │                                       ▼                                                                   │
   │                              FINDINGS REVIEW  [human gate 2: confirm / correct / dismiss / clarify]       │
   │                                       ▼                                                                   │
   │                              SETTLEMENT (deterministic): deductible → copay → sub-limits → benefit limit  │
   └──────────────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                              ▼
                 ┌────────────────────────────────────────────────────────────────────────┐
                 │ FastAPI (API key) ── React UI: Ingest · Claims · Claim detail (Documents,│
                 │ Classification, Master data, Findings, Settlement, Audit) · Dashboard · │
                 │ Config · Live score (vs hidden answer key)      audit log · cost meter  │
                 └────────────────────────────────────────────────────────────────────────┘

CSV/XLSX/JSON upload

Ingest + validate

Document upload

Page classifier

Human gate 1: classification review

Digitise + reconcile

Master dataset · MongoDB + GridFS

LangGraph workflow

policy_rules

duplicates

settlement_recalc

consistency

provider_stats

leakage_assess: calculated vs suspected

explain · policy RAG clause citation · investigator agent

Human gate 2: findings review

Deterministic settlement

Dashboard · Claim detail · Config · Live score · Audit





2.2 Stack (and the one-line "why" for each)
Layer	Choice	Why
Workflow	LangGraph (StateGraph, interrupt(), SQLite/Mongo checkpointer)	visible graph, human gates that pause and resume, state = progress; draw_mermaid() goes on a slide
Models	Kimi K2.5 (Bedrock, ap-south-1) primary; Claude Sonnet 5.5 (Bedrock) fallback; litellm	one key, both reachable (verified 11:10); vision + JSON; retries + cost cap already written
RAG	Titan Text Embeddings v2 (Bedrock) + numpy cosine over policy clauses and rate-card rows	real retrieval with a visible similarity score; zero infrastructure
Extraction	our prompts + Pydantic schemas; json_repair; reconciliation to printed totals	lines are evidence, not guesses
Rules	pure Python engines (duplicates, limits, copay/deductible, package, non-payables, settlement)	every rupee is reproducible and explained
API	FastAPI + API key + audit log	thin, documented at /docs
Data	MongoDB Atlas M0 + GridFS; pandas/openpyxl for files	documents viewable, tech credibility, nothing on the laptop
UI	React + Vite + antd + Tailwind (teammate B)	fast, familiar, tables and filters out of the box
Ops	cloudflared public URL; Docker compose file for "exportable to a client"	judges and the submission need a link
2.3 Guardrails we can honestly claim (each is a file in the repo)
Human gate 1: classification review before anything is extracted. 2. Human gate 2: findings review before settlement; audit row per action. 3. Schema validation on every model answer, one re-ask, then fallback model, then "needs review" (never silent). 4. Totals reconciliation: extracted lines must add up to the printed total within ₹1 or the claim is marked unreconciled. 5. Calculated vs suspected amounts kept separate (the brief demands it). 6. Clause citation: a policy finding carries the clause text and similarity score. 7. Prompt-injection preamble: document text is data; no tools in extraction prompts. 8. Invalid rows are reported, never dropped. 9. Cost cap per claim and a cost meter on screen. 10. API key + per-tenant config. 11. Secrets only in .env; pre-commit grep for key shapes. 12. No PII: synthetic data only; logs carry ids. 13. Evaluation harness with a live score against the hidden answer key. 14. Prompt versioning (version + hash on every result).
3. What we build, by level
Level 1 (gate; demo-ready target 13:30, mentor sign-off by 14:00)
Brief requirement	Feature	Owner
1 Ingestion (CSV/XLSX/JSON + documents), validation, no silent drops	POST /ingest (multipart; any mix of files) → validation report (row, field, problem) → accepted rows into the master dataset; documents stored in GridFS and viewable	D (API) + C (sample data)
2 Policy rule validation: coverage, exclusions, deductible, copay, sub-limits, benefit limit	core/checks/policy_rules.py: per line → rule id, clause, outcome, calculated amount	A
3 Duplicates: exact claim, duplicate line (within/across), near-duplicate, legitimate repeat	core/checks/duplicates.py (name/code normalisation, amount ±0.5%, date keys; repeat-service allow-list by code + distinct dates)	A
4 Leakage assessment: amount, calculated vs suspected, calculation shown	Finding schema + leakage_assess node; the brief's own example (room ₹2,000 over limit × 3 days = ₹6,000) is in the synthetic data	A
5 Dashboard + alert detail + filters	Dashboard, Claims list, Claim detail (Findings tab)	B (UI) + D (GET /dashboard, GET /claims?filters)
Human review	confirm / correct / dismiss / request clarification; audit	D + B
Documents (bonus inside L1 if time)	classifier → review console → digitise → master lines (our strength)	A, after the checks
Level 2 (unlocks ~14:00; forecast from the scenario list; build to 16:45)
Settlement recalculation vs proposed settlement (scenario 3) with history-aware benefit limits; cross-claim duplicates against history; provider peer benchmarking (z-score per code) and related-party patterns (scenario 4); consistency check across documents; clarification workflow; investigator agent with tools; case queue with aging; the document path end-to-end; live score panel.

Level 3 (if it exists; 16:45–17:15 only if L2 is cleared)
Second product (motor) on the same engine; "new insurer in 10 minutes" config demo; graph diagram + cost/latency numbers on the deck.

17:00–18:00 freeze
Deck (8 slides), 2-minute screen recording, public URL, repo hygiene gate, submission on HackCulture before 17:50.

4. Synthetic data (owner C; first cut by 11:50, full by 12:40)
data/synthetic/generate.py (seeded, deterministic) writes CSV + JSON + XLSX plus an answer_key.json that stays out of the UI:

Products: IN-HEALTH-RETAIL (INR; sum insured 5,00,000; room rent 1% of SI/day; ICU 2%; copay 10%; deductible 0; cataract sub-limit 40,000; non-payable consumables list; PED waiting 24 months; exclusions: cosmetic, dental, OPD) and AE-HEALTH-GROUP (AED; annual limit 150,000; deductible AED 50 per OP visit; copay 20% OP, 30% pharmacy; in-network only; dental/optical excluded; DHA-style Activity rows with CPT/drug/service codes, Encounter type, patient share). Policy wording as clause text per product (data/policies/*.md, numbered clauses) for the RAG.
Providers: 8 (6 normal, 1 inflated pricing, 1 with related-party claimants). Claimants: 60. Claims: ~120 with 5–40 invoice lines each; history + settlements for 40 earlier claims.
Planted leakage (each with an answer-key row): exact duplicate claim; duplicate line within a claim; same line across two claims; near-duplicate (date +1, amount +2%, new invoice number); legitimate repeat (6 physio sessions, distinct dates — must NOT flag); room over limit (the brief's ₹2,000 × 3 days); excluded consumable; sub-limit breach; copay missing from the proposed settlement; deductible missed; benefit limit exhausted by history; missing invoice → clarification; provider outlier prices; related-party pattern (shared phone + bank account); a document whose name/policy number belongs to another claim.
Synthetic documents for 8 claims: hospital bill PDF and discharge summary (rendered with reportlab from the same rows, fictional names) so the document path has inputs; one scanned-looking copy (rasterised, slight rotation).
No real data anywhere in the repo or the demo. The real smoke claim stays in hackathon/private/ on your laptop.
5. Team and clock (now ≈ 11:15)
Who	Owns	11:15–11:45	11:45–13:00	13:00–14:00 (lunch overlaps)	14:00–16:45	16:45–18:00
A (you)	core/checks, graph nodes, document path	finalise Finding + master schemas; scrub core/ headers	policy_rules, duplicates, leakage_assess, settlement on synthetic data; unit tests on the answer key	demo L1 with D; mentor sign-off; start document path	document path end-to-end; investigator agent; RAG clauses; consistency + provider checks	freeze; rehearse; answer judge questions
B (UI)	ui/	Vite + antd scaffold; mock JSON from the contract	Claims list + filters, Claim detail (Findings), Dashboard	Ingest screen, review actions, Documents viewer	Classification review, Master data tab, Config, Live score, Audit	polish; recording
C (data)	data/synthetic, data/policies, Atlas	Atlas cluster + connection string; generator v1 (claims, lines, policies)	history, planted leakage, answer key, XLSX/CSV/JSON exports	synthetic PDFs; UAE product; clauses	motor stretch; eval numbers; deck data slides	deck owner
D (API/integration)	backend/, repo, submission	repo + .env + LangGraph skeleton (nodes stubbed) + Mongo repository + /ingest	validation report, /claims, /dashboard, review endpoints, runs/progress, audit	wire A's nodes into the graph; tunnel URL; L1 sign-off	checkpoint/resume, clarification workflow, case queue, Docker compose	repo hygiene gate; HackCulture submission 17:40
Checkpoints: 13:30 L1 demo on synthetic data (ingest → findings → dashboard → review). 16:30 L2 features + document path shown end-to-end. 17:30 freeze; only fixes. Every 60 minutes D merges to main; main must run python -m eval.run --cached green.

6. Brief for the UI teammate (copy-paste; self-contained)
LeakLens UI — a claims-leakage review console. Stack: React 18 + Vite + TypeScript, antd 5, Tailwind 3, lucide-react, react-router, axios. Primary colour #2F7FF2, font Outfit. Talk to the backend at VITE_API_URL (default http://localhost:8000) with header X-API-Key. Start from mock JSON (ui/src/mocks/*.json) that matches the contract below; switch to live when the API is up.

Screens

Ingest — drag-and-drop for CSV/XLSX/JSON and documents (PDF/JPG/PNG); shows the validation report (table: file, row, field, problem, accepted yes/no) and "N claims created".
Claims — table with filters: claim type, provider, leakage category, amount range, date range, status; columns: claim id, claimant (initials), provider, requested, potential leakage (calculated / suspected), severity, status, updated.
Claim detail (tabs): Documents (file list + inline viewer via GET /documents/{id}), Classification (one row per page: page thumbnail, predicted type, confidence; editable dropdown; "Confirm classification" button), Master data (invoice lines table: code, description, qty, unit price, amount, category, page; header totals; a reconciliation badge "lines = printed total ✓/✗"), Findings (one card per finding: check id, severity, amount with a badge Calculated or Suspected, rule applied, the calculation text, evidence quotes with page/row refs, policy clause + similarity; buttons Confirm / Correct (amount input) / Dismiss / Request clarification, note field), Settlement (requested → deductions by rule → copay/deductible → payable; a "proposed vs recalculated" diff), Audit (who did what when).
Dashboard — stat tiles (claims processed, flagged, potential leakage calculated / suspected, awaiting review), bar by leakage category, bar by severity, table of top providers by leakage; all filters from screen 2 apply.
Config — per product: currency, limits (room/day, ICU/day, sub-limits), copay %, deductible, exclusions list, non-payable items list, required documents checklist, auto-triage threshold; JSON editor with Save.
Live score (small panel on the dashboard) — precision / recall / amount recovered vs the hidden answer key: GET /eval/summary.
API contract (JSON)

POST /ingest multipart → { batch_id, claims_created, validation: [{file,row,field,problem,accepted}] }
GET /claims?type=&provider=&category=&min_amount=&max_amount=&from=&to=&status= → [{claim_id, claimant, provider, claim_type, requested_amount, currency, leakage_calculated, leakage_suspected, severity, status, updated_at}]
GET /claims/{id} → { claim, policy, lines[], documents[], classification[], findings[], settlement, audit[] }
POST /claims/{id}/run → { run_id }; GET /claims/{id}/run → { status, steps:[{name,status,started,ended}], cost_usd }
POST /claims/{id}/classification/confirm body [{page_id, document_type}]
POST /claims/{id}/findings/{fid}/review body { action: confirm|correct|dismiss|clarify, amount?, note }
GET /dashboard?…filters → { processed, flagged, leakage_calculated, leakage_suspected, awaiting_review, by_category[], by_severity[], by_provider[] }
GET /config/{product} / PUT /config/{product}; GET /documents/{id} (file stream); GET /eval/summary
Finding: { finding_id, claim_id, check_id, category, severity: low|medium|high, amount, amount_kind: calculated|suspected, currency, rule_id, rule_text, calculation, evidence:[{source, ref, quote}], clause?: {id, text, score}, status: open|confirmed|corrected|dismissed|clarification_requested, reviewer_note }
7. Repo hygiene, submission, deck
Shared repo leaklens/: core/ (scrubbed kit: prompts/, schemas/, engines/, llm/, media/), backend/, ui/, data/synthetic/ + data/policies/, eval/, README.md (what it does, how to run, models used, prompts folder, guardrails table, the one-line reuse sentence), docker-compose.yml, .env.example. Not in the repo: the prep docs, the real claim, caches, .env.
Scrub gate (run by D before every share): grep -riE "trex|insuros|aarogya|knoctio|newarch|langfuse" . must be empty; prompt front matter keeps name/version/sha only; file headers rewritten as plain descriptions.
Submission (17:40): repo link (private GitHub, panel invited), prototype URL (cloudflared tunnel) + 2-minute recording as backup, deck PDF.
Deck (8 slides): problem in one number · what it does (the 5-box flow) · live demo pointers · how the AI is used vs where rules decide · guardrails · the graph diagram + models + cost/latency · results on the synthetic set (precision/recall, amount recovered) · fit for an insurer core (config-only onboarding, API, two markets).
8. Innovation and the judges' hints
Their hint	What we show
Business problem solved strongly	every finding carries an amount, a rule and the evidence; settlement recalculated; clarification instead of invention
Hyper-personalisation	rules, lists, thresholds and auto-triage per product/insurer; two markets, two currencies, same engine
AI on top of an existing product and AI-native	API-first layer a core system can call per claim; AI-native agent (graph + tools + RAG + human gates)
Multiple products at different levels	health IN, health AE, motor stretch; structured input or scanned documents
More usage	review console is a daily tool; queue, aging, audit
Exportable to clients quickly	new insurer = one config JSON + policy wording; Docker compose; no code change
Beyond the brief	policy wording → executable rules with clause citation; document → master data with reconciliation; legitimate-lookalike reasoning; live self-score against an answer key; provider peer benchmarking
9. Verification
L1: python -m eval.run on the synthetic set prints precision/recall per check against answer_key.json; every planted item is found, the legitimate repeat is not flagged, and the room example yields exactly ₹6,000 calculated.
POST /ingest with a deliberately broken CSV returns the row-level report and still creates the valid claims.
Dashboard filters change counts; clicking an alert opens the claim with rule + records.
Review actions write audit rows and change the settlement; a paused graph resumes after the action.
Document path: a synthetic bill PDF → classification review → lines reconcile to its printed total → findings.
Hygiene: scrub grep empty; git status clean of .env, caches and private data; python -m core.llm.ping shows Kimi and Claude on Bedrock.