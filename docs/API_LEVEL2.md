# Level 2 API contract (BE, DOC and UI build to this; change only through the coordinator)

All calls send `X-API-Key`. New optional header **`X-Analyst: <name>`**: the person acting. The backend uses it as the audit
actor and as `decided_by` / `author` (fallback: the API-key actor). CORS must allow it.

## 1. Finding additions (`core/schemas/finding.py`, BE)
```
class Correction(BaseModel):            # recommended settlement correction (req 4)
    action: str        # remove_line | cap_room | reduce_days | fix_arithmetic | cap_sublimit | cap_annual_limit |
                       # apply_copay | apply_deductible | recalc_settlement | reject_claim | hold_for_investigation |
                       # pay_at_peer_median | request_documents
    label: str         # e.g. "Cap the room charge at the daily limit"
    original_amount: float
    corrected_amount: float
    delta: float       # original - corrected (= the finding's amount for calculated findings)
    basis: str         # lines | proposed_settlement | requested
    calculation: str
    rule_id: str
    rule_text: str
    clause_id: Optional[str]

class FindingOriginal(BaseModel):       # frozen at the FIRST decision, never overwritten (req 6)
    amount: float; amount_kind: str; status: str
    correction: Optional[Correction]
    recommendation: Optional[str]; recommendation_note: str
    captured_at: datetime

Finding gets: correction: Optional[Correction]; original: Optional[FindingOriginal]
              decision_reason: str = ""; escalated_to: Optional[str] (senior_reviewer | siu)
              decided_by: Optional[str]; decided_at: Optional[datetime]
              decision_history: List[dict]   # {ts, by, action, from_status, to_status, reason, amount, escalate_to}
FindingStatus gets: ESCALATED = "escalated", CORRECTION_ACCEPTED = "correction_accepted"
effective_amount: escalated -> as open (calculated counts); correction_accepted -> correction.delta (or amount), calculated or suspected
```
`core/checks/corrections.py::attach_corrections(record, findings)` runs at the end of `runner.run_all`: original = sum of
the finding's lines (else the proposed settlement for COPAY/DEDUCTIBLE/SETTLEMENT checks, else the requested amount);
corrected = original − amount. Room on CLM-2026-0033: original 15,000 → corrected 9,000, delta 6,000, ROOM-01, clause 3.1.

## 2. Review (BE) — `POST /claims/{id}/findings/{fid}/review`
Body `{action, reason?, note?, amount?, escalate_to?}`; actions:
| action | status after | rule |
|---|---|---|
| `confirm` | confirmed | — |
| `false_positive` | dismissed | `reason` required → else 400 `{"detail": "A reason is required to mark a finding as a false positive"}` |
| `request_evidence` | clarification_requested | — |
| `escalate` | escalated | `escalate_to` in {senior_reviewer, siu} → else 400 |
| `accept_correction` | correction_accepted | finding must have a correction |
| `correct` | corrected | `amount` and `reason` required |
| `dismiss`, `clarify` | legacy aliases of false_positive (reason optional) / request_evidence | |
Response as today (`findings`, `settlement`) plus `finding`. Audit details: `finding_id, check_id, action, from_status,
to_status, reason, amount, escalate_to, overrides_recommendation (bool), original (on the first decision)`.
Dashboard/list: "awaiting review" counts open + escalated + clarification_requested; list status shows `escalated` when any finding is.

## 3. Workspace data (BE)
- `GET /claims/{id}` adds `policy_terms: [{term, value, clause_id?}]` (annual limit, room/day, ICU/day, copay in/out/pharmacy,
  deductible + basis, each sub-limit, each exclusion, waiting periods, network, non-payable list size) and `notes: [...]` (newest first).
- `POST /claims/{id}/notes` `{text}` → `{note_id, claim_id, author, ts, text}`; audit action `note_added`.

## 4. Related claims (BE) — `GET /claims/{id}/related`
`{claim_id, related: [{claim_id, source: claim|history, claimant_id, claimant_name, provider_id, provider_name, policy_number,
incident_date, requested_amount, currency, status, strength: strong|medium|weak, matches: [{attribute, label, value}], finding_ids}]}`
attributes: `invoice_number` (strong, any policy), `bank_account` / `phone` (strong, different member), `address` (medium,
different member), `same_member_same_provider_30d` (medium), `same_member` (weak). Phone/bank shown masked (last 4). Max 20, strong first.

## 5. Document comparison (BE reads DOC's output) — `GET /claims/{id}/comparison`
```
{claim_id, extracted: bool, extracted_by: "ai-text"|"ai-vision"|null, extracted_at, model, read_seconds,
 documents: [{document_id, name, type, pages}],
 fields: [{field, label, claim_value, document_value, status: match|mismatch|only_in_claim|only_in_document|not_read,
           source: {document_id, document_name, page} | null}],          # claimant_name, policy_number, provider_name,
                                                                         # admission_date, discharge_date, invoice_no, total_amount
 lines: [{status: match|amount_differs|only_in_document|only_in_claim, description, code, claim_amount, document_amount,
          difference, claim_line_id, source: {document_id, document_name, page} | null}],
 summary: {fields_checked, fields_mismatched, lines_matched, lines_only_in_document, lines_only_in_claim,
           lines_amount_differs, claim_total, document_total, total_difference}}
```
Line match: same code when both have one, else normalised description; amounts equal within 1.

**DOC writes the extraction to collection `digitisations`, doc id = claim_id:**
`{claim_id, document_facts: {field: value}, document_fact_sources: {field: {document_id, document_name, page}},
  document_lines: [InvoiceLine dicts with document_id + page], printed_total, reconciled, extracted_by, extracted_at, model, read_seconds}`

## 6. Investigation report (BE) — `GET /claims/{id}/report?format=json|html`
json → attachment `investigation_<claim_id>.json`; html → printable page (inline CSS). Sections: generated_at, generated_by,
claim, policy_terms, settlement (proposed, recalculated, difference, steps), findings (with correction, original,
decision_history, AI recommendation + note), related, comparison, notes, audit (timestamps + users).

## 7. Customer portal (DOC) — `POST /portal/claims` (multipart), `GET /portal/claims/{id}`
Fields: `policy_number`*, `member_id`*, `claim_type`* (inpatient|outpatient|daycare|pharmacy), `incident_date`* (YYYY-MM-DD),
`admission_date`, `discharge_date`, `provider_name`*, `amount_claimed`*, `diagnosis`, `phone`; `files`* (1–10, pdf/jpg/png, ≤10 MB).
422 `{detail: [{field, problem}]}` (unknown policy, member not covered, bad date, no files). 201 `{claim_id, status: "received",
status_url}` in about a second; claim ids `CLM-P-0001…`. Background: classify pages → auto-confirm when every page ≥ 0.85
(else status `waiting_for_analyst`; the analyst confirms in the workspace) → read the bill → read lines become the claim's lines
(`source: "documents"`) → run checks.
`GET /portal/claims/{id}` → `{claim_id, status: received|reading_documents|waiting_for_analyst|checking|under_review|settled|failed,
steps: [{name, label, status, seconds}], documents: [{name, pages, type}], pages_read, lines_read, read_seconds,
amount_claimed, currency, message}` (customer-safe: no findings).
Live score (`/eval/summary`) only scores claims that are in the answer key, so portal claims never count as false alarms.
