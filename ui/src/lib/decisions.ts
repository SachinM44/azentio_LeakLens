import type { AuditRow, Finding, ReviewAction } from '../api/types'

/**
 * Level 2 analyst decisions. The backend review endpoint accepts four actions (confirm | correct | dismiss | clarify),
 * so every decision is sent as one of those AND carries a small tag at the start of the note:
 *     [[LL:{"d":"escalate_siu","by":"Priya","reason":"..."}]] free text
 * The UI reads the tag back to show the real decision, who made it and why. When the backend learns the new
 * decisions, only `toBackend` needs to change.
 */
export type DecisionKind =
  | 'confirm_discrepancy'
  | 'false_positive'
  | 'request_evidence'
  | 'escalate_senior'
  | 'escalate_siu'
  | 'accept_correction'
  | 'override_correction'

export interface DecisionMeta {
  kind: DecisionKind
  label: string
  short: string
  color: string // antd tag colour
  needsReason: boolean
  backendAction: ReviewAction
}

export const DECISIONS: Record<DecisionKind, DecisionMeta> = {
  confirm_discrepancy: { kind: 'confirm_discrepancy', label: 'Confirm discrepancy', short: 'Confirmed', color: 'green', needsReason: false, backendAction: 'confirm' },
  false_positive: { kind: 'false_positive', label: 'Mark as false positive', short: 'False positive', color: 'default', needsReason: true, backendAction: 'dismiss' },
  request_evidence: { kind: 'request_evidence', label: 'Request additional evidence', short: 'Evidence requested', color: 'orange', needsReason: true, backendAction: 'clarify' },
  escalate_senior: { kind: 'escalate_senior', label: 'Escalate to Senior Claims Reviewer', short: 'Escalated: Senior Reviewer', color: 'purple', needsReason: true, backendAction: 'clarify' },
  escalate_siu: { kind: 'escalate_siu', label: 'Escalate to Special Investigation Unit', short: 'Escalated: SIU', color: 'red', needsReason: true, backendAction: 'clarify' },
  accept_correction: { kind: 'accept_correction', label: 'Accept recommended correction', short: 'Correction accepted', color: 'green', needsReason: false, backendAction: 'confirm' },
  override_correction: { kind: 'override_correction', label: 'Override recommendation', short: 'Overridden', color: 'blue', needsReason: true, backendAction: 'correct' },
}

export const FALSE_POSITIVE_REASONS = [
  'Legitimate repeat service (different dates)',
  'Separate valid incident',
  'Documents explain the difference',
  'Provider confirmed by phone',
  'Policy allows this charge',
  'Data entry error in the claim record',
]

const TAG = /^\[\[LL:(\{.*?\})\]\]\s?/s

export interface DecodedNote {
  decision?: DecisionKind
  by?: string
  reason?: string
  text: string
}

export function encodeNote(kind: DecisionKind, by: string, reason: string, text: string): string {
  const meta = { d: kind, by: by || undefined, reason: reason || undefined }
  return `[[LL:${JSON.stringify(meta)}]] ${text}`.trim()
}

export function decodeNote(note?: string | null): DecodedNote {
  const raw = note ?? ''
  const m = raw.match(TAG)
  if (!m) return { text: raw }
  try {
    const meta = JSON.parse(m[1]) as { d?: DecisionKind; by?: string; reason?: string }
    return { decision: meta.d && DECISIONS[meta.d] ? meta.d : undefined, by: meta.by, reason: meta.reason, text: raw.slice(m[0].length) }
  } catch {
    return { text: raw.replace(TAG, '') }
  }
}

/** The decision currently standing on a finding, read from its note (falls back to the backend status). */
export function currentDecision(f: Finding): (DecodedNote & { meta?: DecisionMeta }) | null {
  const note = decodeNote(f.reviewer_note)
  if (note.decision) return { ...note, meta: DECISIONS[note.decision] }
  if (f.status === 'open' || f.status === 'auto_applied') return null
  const fallback: Record<string, DecisionKind> = {
    confirmed: 'confirm_discrepancy', corrected: 'override_correction', dismissed: 'false_positive', clarification_requested: 'request_evidence',
  }
  const kind = fallback[f.status]
  return kind ? { ...note, decision: kind, meta: DECISIONS[kind] } : null
}

/** Strip the tag from any audit-detail note so it reads as plain text. */
export function describeAudit(row: AuditRow): { label: string; by?: string; reason?: string; text: string; amount?: number | null } {
  const d = row.details as Record<string, unknown>
  const note = decodeNote(typeof d.note === 'string' ? d.note : '')
  const meta = note.decision ? DECISIONS[note.decision] : undefined
  const action = row.action.replace(/^review_/, '')
  const label = meta ? meta.label : row.action.startsWith('review_') ? `Decision: ${action}` : row.action.replace(/_/g, ' ')
  return { label, by: note.by, reason: note.reason, text: note.text, amount: typeof d.amount === 'number' ? d.amount : null }
}
