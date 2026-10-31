import type { CheckCategory, FindingStatus, Severity } from '../api/types'

const LOCALES: Record<string, string> = { INR: 'en-IN', AED: 'en-AE' }

export function money(value: number | null | undefined, currency = 'INR'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  try {
    return new Intl.NumberFormat(LOCALES[currency] ?? 'en-US', {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    }).format(value)
  } catch {
    return `${currency} ${value.toLocaleString()}`
  }
}

export function fmtDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function fmtDateTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`
}

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export const CATEGORY_LABEL: Record<CheckCategory, string> = {
  duplicate: 'Duplicates',
  policy_rule: 'Policy rules',
  settlement: 'Settlement arithmetic',
  pattern: 'Patterns',
  evidence: 'Missing evidence',
}

export const CATEGORY_COLOR: Record<CheckCategory, string> = {
  duplicate: '#2ed88e',
  policy_rule: '#16303d',
  settlement: '#0dcaf0',
  pattern: '#ffc107',
  evidence: '#94a3b8',
}

export const SEVERITY_COLOR: Record<Severity, string> = { high: '#dc2626', medium: '#f59e0b', low: '#16a34a' }

export const STATUS_LABEL: Record<FindingStatus, string> = {
  open: 'Open',
  auto_applied: 'Auto-applied',
  confirmed: 'Confirmed',
  corrected: 'Corrected',
  dismissed: 'Dismissed',
  clarification_requested: 'Clarification requested',
}

export const STATUS_COLOR: Record<FindingStatus, string> = {
  open: 'green',
  auto_applied: 'cyan',
  confirmed: 'green',
  corrected: 'purple',
  dismissed: 'default',
  clarification_requested: 'orange',
}

export const CLAIM_TYPES = ['inpatient', 'outpatient', 'pharmacy', 'daycare', 'motor']
export const CLAIM_STATUSES = ['ingested', 'classified', 'extracted', 'checked', 'reviewed', 'settled']

export const DOCUMENT_TYPES = [
  'cancelled_cheque_neft', 'claim_form', 'death_certificate', 'diagnostic_reports', 'discharge_summary',
  'doctors_certificate_surgery', 'doctors_notes', 'implant_stickers_invoices', 'interim_running_bill',
  'itemized_final_hospital_bill', 'kyc_document', 'kyc_form', 'medicine_pharmacy_bills', 'mlc_fir_report',
  'operation_theatre_notes', 'other_documents', 'patient_accounts_documents', 'policy_schedule', 'pre_auth_form',
  'prescriptions', 'summary_final_hospital_bill', 'undertaking_form',
]

/** Short plain-English names for the check ids shown on cards and charts. */
export const CHECK_LABEL: Record<string, string> = {
  DUPLICATE_CLAIM: 'Duplicate claim',
  DUPLICATE_LINE: 'Duplicate line',
  CROSS_CLAIM_DUPLICATE_LINE: 'Already paid on another claim',
  NEAR_DUPLICATE: 'Near-duplicate',
  COVERAGE_INACTIVE: 'Cover not active',
  EXCLUDED_SERVICE: 'Excluded service',
  NON_PAYABLE_ITEM: 'Non-payable item',
  ROOM_LIMIT_EXCEEDED: 'Room limit exceeded',
  SUBLIMIT_EXCEEDED: 'Sub-limit exceeded',
  BENEFIT_LIMIT_EXCEEDED: 'Benefit limit exceeded',
  OUT_OF_NETWORK: 'Out of network',
  WAITING_PERIOD: 'Inside waiting period',
  COPAY_NOT_APPLIED: 'Co-pay not applied',
  DEDUCTIBLE_NOT_APPLIED: 'Deductible not applied',
  SETTLEMENT_MISMATCH: 'Settlement mismatch',
  QUANTITY_VS_STAY: 'Days billed vs stay',
  DATE_OUTSIDE_EPISODE: 'Date outside admission',
  ARITHMETIC_MISMATCH: 'Arithmetic mismatch',
  PROVIDER_PRICE_OUTLIER: 'Provider price outlier',
  RELATED_PARTY_PATTERN: 'Related-party pattern',
  CONSISTENCY_MISMATCH: 'Documents disagree',
  MISSING_EVIDENCE: 'Missing evidence',
}

export const checkLabel = (id: string): string => CHECK_LABEL[id] ?? titleCase(id.toLowerCase())
