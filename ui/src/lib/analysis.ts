import type { CaseNote, Claim, ClaimDetail, Finding, InvoiceLine } from '../api/types'
import { describeAudit, currentDecision } from './decisions'
import { checkLabel, fmtDateTime, money } from './format'

// ---------------------------------------------------------------------------------------------- recommended corrections

export interface Correction {
  headline: string
  original: number
  corrected: number
  calculation: string
  ruleId: string
  ruleText: string
  clause?: string
  conditional: boolean // suspected findings: the correction applies only if a reviewer confirms the issue
  basis: string // what "original" refers to
}

const HEADLINE: Record<string, string> = {
  DUPLICATE_LINE: 'Remove the duplicate line',
  CROSS_CLAIM_DUPLICATE_LINE: 'Remove the charge already paid on another claim',
  DUPLICATE_CLAIM: 'Reject the duplicate claim',
  NEAR_DUPLICATE: 'Hold the possible duplicate until it is explained',
  NON_PAYABLE_ITEM: 'Remove the non-payable item',
  EXCLUDED_SERVICE: 'Remove the excluded service',
  ROOM_LIMIT_EXCEEDED: 'Cap the room charge at the daily limit',
  SUBLIMIT_EXCEEDED: 'Cap the charge at the sub-limit',
  BENEFIT_LIMIT_EXCEEDED: 'Cap the payment at the remaining annual limit',
  COPAY_NOT_APPLIED: 'Apply the co-pay',
  DEDUCTIBLE_NOT_APPLIED: 'Apply the deductible',
  SETTLEMENT_MISMATCH: 'Reduce the settlement to the recalculated amount',
  QUANTITY_VS_STAY: 'Reduce per-day items to the days of the stay',
  DATE_OUTSIDE_EPISODE: 'Remove the line dated outside the admission',
  ARITHMETIC_MISMATCH: 'Correct the line amount to quantity × unit price',
  COVERAGE_INACTIVE: 'Decline: the incident is outside the policy cover',
  WAITING_PERIOD: 'Decline: inside the waiting period',
  OUT_OF_NETWORK: 'Apply out-of-network terms',
  PROVIDER_PRICE_OUTLIER: 'Reduce the price to the peer median',
  RELATED_PARTY_PATTERN: 'Hold payment pending a related-party review',
  CONSISTENCY_MISMATCH: 'Hold payment until the documents are reconciled',
}

/** A specific adjustment for a finding: original amount → corrected amount, the calculation and the supporting rule. */
export function buildCorrection(f: Finding, detail: ClaimDetail): Correction | null {
  if (f.amount <= 0) return null
  const settlementLevel = ['COPAY_NOT_APPLIED', 'DEDUCTIBLE_NOT_APPLIED', 'SETTLEMENT_MISMATCH'].includes(f.check_id)
  const lineTotal = f.line_ids.reduce((sum, id) => sum + (detail.lines.find((l) => l.line_id === id)?.amount ?? 0), 0)
  let original: number
  let basis: string
  if (settlementLevel && detail.claim.proposed_settlement != null) {
    original = detail.claim.proposed_settlement
    basis = "the handler's proposed settlement"
  } else if (lineTotal > 0) {
    original = lineTotal
    basis = f.line_ids.length > 1 ? `${f.line_ids.length} invoice lines` : 'the invoice line'
  } else {
    original = detail.claim.requested_amount
    basis = 'the requested amount'
  }
  const corrected = Math.max(0, Math.round((original - f.amount) * 100) / 100)
  return {
    headline: HEADLINE[f.check_id] ?? `Reduce by ${checkLabel(f.check_id).toLowerCase()}`,
    original, corrected, basis,
    calculation: `${money(original, f.currency)} − ${money(f.amount, f.currency)} = ${money(corrected, f.currency)}${f.calculation ? `   (${f.calculation})` : ''}`,
    ruleId: f.rule_id, ruleText: f.rule_text, clause: f.clause ? `Clause ${f.clause.clause_id}: ${f.clause.text}` : undefined,
    conditional: f.amount_kind === 'suspected',
  }
}

// ---------------------------------------------------------------------------------------------- cross-claim correlation

export interface Match { attribute: string; mine: string; theirs: string; strength: 'strong' | 'medium' | 'weak' }

const norm = (v?: string | null) => (v ?? '').trim().toLowerCase()
const mask = (v: string) => (v.length > 4 ? `${'•'.repeat(Math.min(6, v.length - 4))}${v.slice(-4)}` : v)

/** Which attributes connect two claims, and how strongly. */
export function matchClaims(mine: Claim, theirs: Claim): Match[] {
  const out: Match[] = []
  const sharedInvoices = mine.invoice_numbers.filter((i) => theirs.invoice_numbers.map(norm).includes(norm(i)))
  if (sharedInvoices.length) out.push({ attribute: 'Same invoice number', mine: sharedInvoices.join(', '), theirs: sharedInvoices.join(', '), strength: 'strong' })
  if (mine.policy_number !== theirs.policy_number && sharedInvoices.length) {
    out.push({ attribute: 'Different policies, same invoice', mine: mine.policy_number, theirs: theirs.policy_number, strength: 'strong' })
  }
  if (mine.claimant_id === theirs.claimant_id) out.push({ attribute: 'Same member', mine: mine.claimant_id, theirs: theirs.claimant_id, strength: 'medium' })
  if (mine.policy_number === theirs.policy_number) out.push({ attribute: 'Same policy', mine: mine.policy_number, theirs: theirs.policy_number, strength: 'weak' })
  if (mine.provider_id === theirs.provider_id) out.push({ attribute: 'Same provider', mine: mine.provider_name || mine.provider_id, theirs: theirs.provider_name || theirs.provider_id, strength: 'weak' })
  if (mine.claimant_id !== theirs.claimant_id) {
    if (mine.contact_phone && norm(mine.contact_phone) === norm(theirs.contact_phone)) out.push({ attribute: 'Shared phone number', mine: mask(mine.contact_phone), theirs: mask(theirs.contact_phone ?? ''), strength: 'strong' })
    if (mine.bank_account && norm(mine.bank_account) === norm(theirs.bank_account)) out.push({ attribute: 'Shared bank account', mine: mask(mine.bank_account), theirs: mask(theirs.bank_account ?? ''), strength: 'strong' })
    if (mine.address && norm(mine.address) === norm(theirs.address)) out.push({ attribute: 'Shared address', mine: mine.address, theirs: theirs.address ?? '', strength: 'medium' })
  }
  const days = Math.abs((new Date(mine.incident_date).getTime() - new Date(theirs.incident_date).getTime()) / 86_400_000)
  if (!Number.isNaN(days) && days <= 3 && mine.provider_id === theirs.provider_id) {
    out.push({ attribute: 'Incident dates close together', mine: mine.incident_date, theirs: theirs.incident_date, strength: 'medium' })
  }
  const diff = Math.abs(mine.requested_amount - theirs.requested_amount) / Math.max(1, theirs.requested_amount)
  if (diff <= 0.03) out.push({ attribute: 'Almost the same amount', mine: money(mine.requested_amount, mine.currency), theirs: money(theirs.requested_amount, theirs.currency), strength: 'medium' })
  return out
}

// ---------------------------------------------------------------------------------------------- document vs claim comparison

export type CompareStatus = 'match' | 'mismatch' | 'missing_in_document' | 'missing_in_claim'
export interface CompareRow { key: string; field: string; claim: string; document: string; status: CompareStatus; source?: string; note?: string }

const eqText = (a: string, b: string) => norm(a).replace(/[^a-z0-9]/g, '') === norm(b).replace(/[^a-z0-9]/g, '')
const FIELD_LABEL: Record<string, string> = {
  claimant_name: 'Claimant name', policy_number: 'Policy number', provider_name: 'Provider', admission_date: 'Admission date',
  discharge_date: 'Discharge date', invoice_no: 'Invoice number', net_payable: 'Net payable',
}

function claimValueFor(field: string, c: Claim, d: ClaimDetail): string | undefined {
  switch (field) {
    case 'claimant_name': return c.claimant_name || undefined
    case 'policy_number': return c.policy_number
    case 'provider_name': return c.provider_name || undefined
    case 'admission_date': return c.admission_date ?? undefined
    case 'discharge_date': return c.discharge_date ?? undefined
    case 'invoice_no': return c.invoice_numbers.join(', ') || undefined
    case 'net_payable': return String(d.lines.reduce((s, l) => s + l.amount, 0))
    default: return undefined
  }
}

export function buildComparison(d: ClaimDetail): CompareRow[] {
  const rows: CompareRow[] = []
  const cur = d.claim.currency
  const seen = new Set<string>()

  // 1) header facts read off the documents (when the backend sends them), each with its source
  for (const fact of d.document_facts ?? []) {
    const claimVal = claimValueFor(fact.field, d.claim, d)
    const label = FIELD_LABEL[fact.field] ?? fact.field
    const source = fact.document_name ? `${fact.document_name}${fact.page ? `, p.${fact.page}` : ''}` : fact.document_id
    const isMoney = fact.field === 'net_payable'
    const same = claimVal === undefined ? false
      : isMoney ? Math.abs(Number(claimVal) - Number(fact.value.replace(/[^0-9.-]/g, ''))) <= 1
      : fact.field.endsWith('_date') ? claimVal.slice(0, 10) === fact.value.slice(0, 10) : eqText(claimVal, fact.value)
    seen.add(label)
    rows.push({
      key: `fact-${fact.field}`, field: label,
      claim: claimVal === undefined ? '—' : isMoney ? money(Number(claimVal), cur) : claimVal,
      document: isMoney ? money(Number(fact.value.replace(/[^0-9.-]/g, '')), cur) : fact.value,
      status: claimVal === undefined ? 'missing_in_claim' : same ? 'match' : 'mismatch', source,
      note: isMoney ? 'Claim value is the sum of the invoice lines' : undefined,
    })
  }

  // 2) discrepancies the consistency check already found: "claim 'A' vs document 'B'"
  for (const f of d.findings.filter((x) => x.check_id === 'CONSISTENCY_MISMATCH')) {
    for (const e of f.evidence.filter((x) => x.source === 'document')) {
      const m = e.quote.match(/claim '(.*)' vs document '(.*)'/)
      const label = e.ref.replace(/^./, (c) => c.toUpperCase())
      if (!m || seen.has(label)) continue
      seen.add(label)
      rows.push({ key: `cons-${e.ref}`, field: label, claim: m[1], document: m[2], status: 'mismatch', source: 'consistency check', note: f.reason })
    }
  }

  // 3) the printed total against the lines and the requested amount
  if (d.printed_total != null) {
    const sum = d.lines.reduce((s, l) => s + l.amount, 0)
    if (!seen.has('Net payable')) {
      rows.push({ key: 'printed', field: 'Bill total', claim: money(sum, cur), document: money(d.printed_total, cur),
        status: Math.abs(sum - d.printed_total) <= 1 ? 'match' : 'mismatch', source: 'printed on the bill', note: 'Invoice lines added up vs the total printed on the bill' })
    }
    if (Math.abs(d.claim.requested_amount - d.printed_total) > 1) {
      rows.push({ key: 'requested', field: 'Requested amount', claim: money(d.claim.requested_amount, cur), document: money(d.printed_total, cur),
        status: 'mismatch', source: 'printed on the bill', note: 'The amount claimed differs from the bill total' })
    }
  }

  // 4) document lines against the invoice lines (service, date and amount)
  const docLines = d.document_lines ?? []
  const used = new Set<number>()
  for (const line of d.lines as InvoiceLine[]) {
    const idx = docLines.findIndex((dl, i) => !used.has(i) && eqText(dl.description, line.description))
    if (idx < 0) {
      if (docLines.length) rows.push({ key: `l-${line.line_id}`, field: `Line: ${line.description}`, claim: money(line.amount, cur), document: '—', status: 'missing_in_document', note: 'Billed in the claim but not found on the document' })
      continue
    }
    used.add(idx)
    const dl = docLines[idx]
    const source = dl.document_name ? `${dl.document_name}${dl.page ? `, p.${dl.page}` : ''}` : dl.document_id
    const amountOk = Math.abs(dl.amount - line.amount) <= 1
    const dateOk = !dl.service_date || !line.service_date || dl.service_date.slice(0, 10) === line.service_date.slice(0, 10)
    rows.push({
      key: `l-${line.line_id}`, field: `Line: ${line.description}`,
      claim: `${money(line.amount, cur)}${line.service_date ? ` · ${line.service_date}` : ''}`,
      document: `${money(dl.amount, cur)}${dl.service_date ? ` · ${dl.service_date.slice(0, 10)}` : ''}`,
      status: amountOk && dateOk ? 'match' : 'mismatch', source,
      note: !amountOk ? `Amount differs by ${money(Math.abs(dl.amount - line.amount), cur)}` : !dateOk ? 'Service date differs' : undefined,
    })
  }
  docLines.forEach((dl, i) => {
    if (used.has(i)) return
    rows.push({ key: `d-${i}`, field: `Line: ${dl.description}`, claim: '—', document: money(dl.amount, cur), status: 'missing_in_claim',
      source: dl.document_name ? `${dl.document_name}${dl.page ? `, p.${dl.page}` : ''}` : dl.document_id, note: 'On the document but not billed in the claim' })
  })
  return rows
}

// ---------------------------------------------------------------------------------------------- evidence history

export interface TimelineEvent {
  key: string
  ts: string
  kind: 'detected' | 'ai' | 'decision' | 'override' | 'note' | 'system'
  title: string
  detail?: string
  by?: string
  findingId?: string
  amount?: number | null
  extra?: string
}

/** Everything that happened on the case, oldest first: detections with their original calculation, AI
 *  recommendations, decisions, overrides (with the original recommendation kept), notes and system actions. */
export function buildTimeline(d: ClaimDetail, notes: CaseNote[]): TimelineEvent[] {
  const events: TimelineEvent[] = []
  for (const f of d.findings) {
    const ts = f.created_at ?? d.run?.started ?? d.audit[0]?.ts ?? new Date(0).toISOString()
    events.push({ key: `det-${f.finding_id}`, ts, kind: 'detected', findingId: f.finding_id, amount: f.amount,
      title: `Issue detected: ${checkLabel(f.check_id)}`, detail: `${f.rule_id}: ${f.calculation || f.reason}`, by: 'LeakLens rules',
      extra: f.amount_kind === 'calculated' ? 'Calculated amount' : 'Suspected amount' })
    if (f.recommendation) {
      events.push({ key: `ai-${f.finding_id}`, ts, kind: 'ai', findingId: f.finding_id, by: 'Investigator agent',
        title: `AI recommendation: ${f.recommendation}${f.recommendation_confidence != null ? ` (${Math.round(f.recommendation_confidence * 100)}% confidence)` : ''}`,
        detail: f.recommendation_note })
    }
  }
  for (const row of d.audit) {
    const info = describeAudit(row)
    const isReview = row.action.startsWith('review_')
    const details = row.details as Record<string, unknown>
    const fid = typeof details.finding_id === 'string' ? details.finding_id : undefined
    const finding = fid ? d.findings.find((f) => f.finding_id === fid) : undefined
    const overridden = isReview && row.action === 'review_correct'
    events.push({
      key: row.audit_id, ts: row.ts, kind: overridden ? 'override' : isReview ? 'decision' : 'system', findingId: fid,
      title: info.label, by: info.by ?? row.actor, amount: info.amount,
      detail: [info.reason ? `Reason: ${info.reason}` : '', info.text].filter(Boolean).join(' · ') || (isReview ? undefined : JSON.stringify(row.details)),
      extra: overridden && finding ? `Original recommendation kept: ${finding.recommendation ?? 'remove'} ${money(finding.amount, finding.currency)}` : undefined,
    })
  }
  for (const n of notes) events.push({ key: n.note_id, ts: n.ts, kind: 'note', title: 'Analyst note', detail: n.text, by: n.author })
  return events.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())
}

// ---------------------------------------------------------------------------------------------- investigation report

export function buildReport(d: ClaimDetail, notes: CaseNote[], related: { claim_id: string; matches: Match[] }[], analyst: string) {
  const comparison = buildComparison(d)
  return {
    report_type: 'LeakLens investigation report',
    generated_at: new Date().toISOString(),
    generated_by: analyst || 'unknown analyst',
    claim: d.claim,
    policy: d.policy,
    summary: {
      requested_amount: d.claim.requested_amount, currency: d.claim.currency,
      calculated_leakage: d.summary.leakage_calculated, suspected_leakage: d.summary.leakage_suspected,
      severity: d.summary.severity, findings: d.findings.length, open_findings: d.summary.open_findings,
    },
    findings: d.findings.map((f) => {
      const decision = currentDecision(f)
      const c = buildCorrection(f, d)
      return {
        finding_id: f.finding_id, check: f.check_id, severity: f.severity, amount_kind: f.amount_kind, amount: f.amount,
        rule: { id: f.rule_id, text: f.rule_text, clause: f.clause ?? null }, calculation: f.calculation, reason: f.reason,
        evidence: f.evidence, related_claims: f.related_claim_ids,
        ai_recommendation: f.recommendation ? { recommendation: f.recommendation, confidence: f.recommendation_confidence, note: f.recommendation_note } : null,
        recommended_correction: c ? { headline: c.headline, original: c.original, corrected: c.corrected, calculation: c.calculation, conditional: c.conditional } : null,
        decision: decision ? { decision: decision.meta?.label, by: decision.by ?? null, reason: decision.reason ?? null, note: decision.text, corrected_amount: f.corrected_amount ?? null } : null,
        original_amount_retained: f.amount,
      }
    }),
    related_claims: related,
    document_comparison: comparison,
    settlement: d.settlement,
    notes,
    audit_trail: buildTimeline(d, notes).map((e) => ({ ts: e.ts, kind: e.kind, title: e.title, detail: e.detail ?? null, by: e.by ?? null, amount: e.amount ?? null })),
  }
}

export type InvestigationReport = ReturnType<typeof buildReport>

export function downloadJson(report: InvestigationReport, claimId: string) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `investigation-${claimId}.json`
  a.click()
  URL.revokeObjectURL(url)
}

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))

/** A readable, printable version (Save as PDF from the print dialog). */
export function openPrintableReport(r: InvestigationReport) {
  const cur = r.claim.currency
  const rows = (items: string[][]) => items.map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Investigation ${esc(r.claim.claim_id)}</title>
<style>body{font-family:Poppins,Arial,sans-serif;color:#16303d;margin:32px;font-size:13px}h1{margin:0}h2{margin:26px 0 8px;border-bottom:2px solid #2ed88e;padding-bottom:4px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #dbe4ea;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f4f7f9}.m{color:#6b7c88}</style></head><body>
<h1>Investigation report: ${esc(r.claim.claim_id)}</h1><div class="m">Generated ${esc(fmtDateTime(r.generated_at))} by ${esc(r.generated_by)}</div>
<h2>Claim</h2><table>${rows([
    ['Claimant', `${r.claim.claimant_name ?? ''} (${r.claim.claimant_id})`], ['Policy', r.claim.policy_number], ['Provider', r.claim.provider_name || r.claim.provider_id],
    ['Type / incident', `${r.claim.claim_type} / ${r.claim.incident_date}`], ['Requested', money(r.summary.requested_amount, cur)],
    ['Calculated leakage', money(r.summary.calculated_leakage, cur)], ['Suspected leakage', money(r.summary.suspected_leakage, cur)]])}</table>
<h2>Findings and decisions</h2><table><tr><th>Finding</th><th>Amount</th><th>Rule and calculation</th><th>AI recommendation</th><th>Recommended correction</th><th>Decision</th></tr>${r.findings.map((f) => `<tr>
<td>${esc(f.check)}<br><span class="m">${esc(f.finding_id)}<br>${esc(f.severity)} · ${esc(f.amount_kind)}</span></td><td>${esc(money(f.amount, cur))}</td>
<td>${esc(f.rule.id)}: ${esc(f.rule.text)}<br><span class="m">${esc(f.calculation)}</span></td>
<td>${f.ai_recommendation ? `${esc(f.ai_recommendation.recommendation)} (${Math.round((f.ai_recommendation.confidence ?? 0) * 100)}%)<br><span class="m">${esc(f.ai_recommendation.note)}</span>` : '—'}</td>
<td>${f.recommended_correction ? `${esc(f.recommended_correction.headline)}<br>${esc(money(f.recommended_correction.original, cur))} → ${esc(money(f.recommended_correction.corrected, cur))}` : '—'}</td>
<td>${f.decision ? `${esc(f.decision.decision)}<br><span class="m">${esc(f.decision.by ?? '')} ${esc(f.decision.reason ?? '')} ${esc(f.decision.note)}</span>` : 'Open'}</td></tr>`).join('')}</table>
<h2>Document comparison</h2><table><tr><th>Field</th><th>Claim</th><th>Document</th><th>Result</th><th>Source</th></tr>${rows(r.document_comparison.map((c) => [c.field, c.claim, c.document, c.status, c.source ?? '']))}</table>
<h2>Related claims</h2>${r.related_claims.length ? `<table>${rows(r.related_claims.map((c) => [c.claim_id, c.matches.map((m) => m.attribute).join('; ')]))}</table>` : '<p class="m">None.</p>'}
<h2>Analyst notes</h2>${r.notes.length ? `<table>${rows(r.notes.map((n) => [fmtDateTime(n.ts), n.author, n.text]))}</table>` : '<p class="m">None.</p>'}
<h2>Audit trail</h2><table>${rows(r.audit_trail.map((e) => [fmtDateTime(e.ts), e.by ?? '', e.title, e.detail ?? '']))}</table>
<script>window.onload=function(){window.print()}</script></body></html>`
  const w = window.open('', '_blank')
  if (w) { w.document.write(html); w.document.close() }
}
