// Mirrors core/schemas/* and the response shapes in backend/views.py. Keep in sync with docs/PLAN.md section 4.

export type Severity = 'low' | 'medium' | 'high'
export type AmountKind = 'calculated' | 'suspected'
export type FindingStatus = 'open' | 'auto_applied' | 'confirmed' | 'corrected' | 'dismissed' | 'clarification_requested'
export type CheckCategory = 'duplicate' | 'policy_rule' | 'settlement' | 'pattern' | 'evidence'
export type ReviewAction = 'confirm' | 'correct' | 'dismiss' | 'clarify'

export interface Evidence {
  source: string
  ref: string
  quote: string
}

export interface ClauseRef {
  clause_id: string
  text: string
  score: number
}

export interface Finding {
  finding_id: string
  claim_id: string
  check_id: string
  category: CheckCategory
  severity: Severity
  amount: number
  amount_kind: AmountKind
  currency: string
  rule_id: string
  rule_text: string
  calculation: string
  reason: string
  line_ids: string[]
  evidence: Evidence[]
  clause?: ClauseRef | null
  related_claim_ids: string[]
  status: FindingStatus
  reviewer_note: string
  corrected_amount?: number | null
  created_at?: string
  /** Investigator agent (suspected findings): confirm | dismiss | clarify */
  recommendation?: string | null
  recommendation_confidence?: number | null
  recommendation_note?: string
}

export interface ClaimSummary {
  claim_id: string
  claimant: string
  claimant_id?: string
  provider: string
  provider_id?: string
  claim_type: string
  product_id?: string
  incident_date: string
  requested_amount: number
  currency: string
  leakage_calculated: number
  leakage_suspected: number
  severity: Severity | null
  findings: number
  open_findings: number
  status: string
  updated_at?: string
}

export interface ClaimFilters {
  type?: string
  provider?: string
  category?: string
  min_amount?: number
  max_amount?: number
  from?: string
  to?: string
  status?: string
}

export interface Claim {
  claim_id: string
  policy_number: string
  product_id: string
  claimant_id: string
  claimant_name?: string
  provider_id: string
  provider_name?: string
  claim_type: string
  incident_date: string
  admission_date?: string | null
  discharge_date?: string | null
  diagnosis?: string | null
  diagnosis_code?: string | null
  room_category?: string | null
  requested_amount: number
  proposed_settlement?: number | null
  currency: string
  invoice_numbers: string[]
  status: string
  source?: string
  contact_phone?: string | null
  bank_account?: string | null
  address?: string | null
  extra?: Record<string, string>
}

export interface InvoiceLine {
  line_id: string
  claim_id: string
  invoice_no: string
  serial_no: number
  service_date?: string | null
  code?: string | null
  description: string
  category?: string | null
  quantity: number
  unit_price?: number | null
  amount: number
  provider_id?: string | null
  document_id?: string | null
  page?: number | null
  notes?: string | null
}

export interface Sublimit {
  sublimit_id: string
  name: string
  limit: number
  basis: string
  clause_id?: string | null
}

export interface Exclusion {
  exclusion_id: string
  text: string
  clause_id?: string | null
}

export interface Policy {
  policy_number: string
  product_id: string
  holder_id: string
  members: string[]
  start_date: string
  end_date: string
  currency: string
  annual_limit: number
  deductible: { amount: number; basis: string }
  copay: { inpatient_pct: number; outpatient_pct: number; pharmacy_pct: number }
  room_rent_limit_per_day?: number | null
  icu_limit_per_day?: number | null
  sublimits: Sublimit[]
  exclusions: Exclusion[]
  non_payable_items: string[]
  network_provider_ids: string[]
  waiting_period_days: number
}

export interface DocumentView {
  id: string
  name?: string
  type?: string | null
  pages: number
  mime?: string
  uploaded_at?: string
}

export interface ClassificationRow {
  document_id: string
  document_name?: string
  page_id: string
  page: number
  predicted_type?: string | null
  confidence?: number | null
  confirmed_type?: string | null
  predicted_by?: string | null
}

export interface Deduction {
  finding_id: string
  check_id: string
  amount: number
  reason: string
}

export interface Settlement {
  claim_id: string
  currency: string
  requested_amount: number
  lines_total: number
  deductions: Deduction[]
  after_deductions: number
  deductible_amount: number
  copay_pct: number
  copay_amount: number
  benefit_cap_applied: number
  payable: number
  patient_pays: number
  proposed_settlement?: number | null
  difference?: number | null
  steps: string[]
}

export interface RunStep {
  name: string
  status: string
  started?: string
  ended?: string | null
  error?: string
}

export interface Run {
  run_id: string | null
  claim_id: string
  status: string
  steps: RunStep[]
  cost_usd: number
  cost_cap_usd?: number
  paused_at?: string | null
  error?: string | null
  started?: string
  ended?: string | null
}

export interface AuditRow {
  audit_id: string
  ts: string
  actor: string
  action: string
  claim_id: string | null
  details: Record<string, unknown>
}

export interface ProductConfig {
  product_id: string
  name: string
  insurer: string
  market: string
  currency: string
  required_documents: Record<string, string[]>
  non_payable_items: string[]
  auto_triage_threshold: number
  near_duplicate_amount_tolerance_pct: number
  near_duplicate_days: number
  repeatable_service_codes: string[]
  provider_outlier_zscore: number
  policy_wording_file?: string | null
}

/** What the document says, with a pointer back to where it was read (Level 2: values keep their source). */
export interface DocumentFact {
  field: string
  value: string
  document_id?: string
  document_name?: string
  page?: number | null
}

export interface DocumentLine {
  description: string
  code?: string | null
  quantity?: number | null
  unit_price?: number | null
  amount: number
  service_date?: string | null
  document_id?: string
  document_name?: string
  page?: number | null
}

/** Claim-level analyst note. */
export interface CaseNote {
  note_id: string
  claim_id: string
  author: string
  text: string
  ts: string
  local?: boolean
}

export interface ClaimDetail {
  claim: Claim
  policy: Policy | null
  product: ProductConfig
  lines: InvoiceLine[]
  documents: DocumentView[]
  classification: ClassificationRow[]
  findings: Finding[]
  settlement: Settlement | null
  audit: AuditRow[]
  run: Run | null
  summary: ClaimSummary
  reconciled?: boolean | null
  printed_total?: number | null
  /** Optional: values read off the documents. When absent the UI derives what it can from the findings. */
  document_facts?: DocumentFact[]
  document_lines?: DocumentLine[]
  notes?: CaseNote[]
}

export interface ValidationIssue {
  file: string
  row?: number | null
  field: string
  problem: string
  accepted: boolean
}

export interface IngestResult {
  batch_id: string
  counts: Record<string, number>
  claims_created: number
  claims_affected: string[]
  documents: { id?: string; document_id?: string; name?: string; claim_id?: string; pages?: number }[]
  validation: ValidationIssue[]
}

export interface Dashboard {
  claims: number
  processed: number
  flagged: number
  leakage_calculated: number
  leakage_suspected: number
  awaiting_review: number
  by_category: { category: string; count: number; amount_calculated: number; amount_suspected: number }[]
  by_severity: { severity: Severity; count: number; amount: number }[]
  by_provider: {
    provider_id: string
    provider_name: string
    claims: number
    flagged: number
    leakage_calculated: number
    leakage_suspected: number
  }[]
  by_check: { check_id: string; count: number; amount_calculated: number; amount_suspected: number }[]
}

export interface Rates {
  tp: number
  fp: number
  fn: number
  precision: number | null
  recall: number | null
}

export type EvalSummary =
  | { available: false; reason?: string }
  | {
      available: true
      planted: number
      must_not_flag: number
      overall: Rates
      amount_planted: number
      amount_recovered: number
      look_alikes_wrongly_flagged: { claim_id: string; check_id: string; note: string }[]
      by_check: Record<string, Rates>
    }

export interface ReviewResponse {
  claim_id: string
  run_id: string | null
  findings: Finding[]
  settlement: Settlement | null
  summary: ClaimSummary | null
}
