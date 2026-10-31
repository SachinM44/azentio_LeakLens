// In-memory stand-in for the API (Settings → "Use mock data"). Same shapes as docs/PLAN.md section 4, so the UI can be
// built and demoed before the backend is up. Synthetic people, providers and amounts only.
import type {
  AuditRow, CaseNote, Claim, ClaimDetail, ClaimFilters, ClaimSummary, ClassificationRow, Dashboard, EvalSummary, Finding,
  IngestResult, InvoiceLine, Policy, ProductConfig, ReviewAction, Run, Settlement, Severity,
} from './types'

const delay = (ms = 250) => new Promise((r) => setTimeout(r, ms))
const iso = () => new Date().toISOString()

const POLICY: Policy = {
  policy_number: 'POL-IN-7781', product_id: 'IN-HEALTH-RETAIL', holder_id: 'H-100', members: ['M-201', 'M-202'],
  start_date: '2026-04-01', end_date: '2027-03-31', currency: 'INR', annual_limit: 500000,
  deductible: { amount: 2000, basis: 'per_claim' }, copay: { inpatient_pct: 10, outpatient_pct: 20, pharmacy_pct: 10 },
  room_rent_limit_per_day: 3000, icu_limit_per_day: 6000,
  sublimits: [
    { sublimit_id: 'CATARACT', name: 'Cataract surgery', limit: 40000, basis: 'per_claim', clause_id: '4.3' },
    { sublimit_id: 'PHYSIO', name: 'Physiotherapy sessions', limit: 12, basis: 'sessions_per_year', clause_id: '4.7' },
  ],
  exclusions: [
    { exclusion_id: 'COSMETIC', text: 'Cosmetic and aesthetic procedures are not covered.', clause_id: '5.2' },
    { exclusion_id: 'DENTAL', text: 'Dental treatment other than following an accident.', clause_id: '5.4' },
  ],
  non_payable_items: ['Gloves', 'Mask', 'Admission kit', 'Service charge'], network_provider_ids: [], waiting_period_days: 30,
}

const PRODUCT: ProductConfig = {
  product_id: 'IN-HEALTH-RETAIL', name: 'Retail Health (India)', insurer: 'Synthetic Mutual', market: 'IN', currency: 'INR',
  required_documents: { inpatient: ['claim_form', 'discharge_summary', 'itemized_final_hospital_bill'], outpatient: ['claim_form', 'prescriptions'] },
  non_payable_items: ['Gloves', 'Mask', 'Admission kit', 'Service charge'], auto_triage_threshold: 500,
  near_duplicate_amount_tolerance_pct: 2, near_duplicate_days: 3, repeatable_service_codes: ['PHY-01', 'DIA-02'],
  provider_outlier_zscore: 2.5, policy_wording_file: 'in-health-retail.md',
}

const line = (claim: string, inv: string, n: number, desc: string, qty: number, price: number, cat: string, date: string, code?: string): InvoiceLine => ({
  line_id: `${claim}:${inv}:${n}`, claim_id: claim, invoice_no: inv, serial_no: n, service_date: date, code: code ?? null, description: desc,
  category: cat, quantity: qty, unit_price: price, amount: qty * price, provider_id: null, document_id: null, page: 1, notes: null,
})

const mk = (c: Partial<Claim> & Pick<Claim, 'claim_id' | 'claimant_name' | 'provider_id' | 'provider_name' | 'claim_type' | 'incident_date' | 'requested_amount'>): Claim => ({
  policy_number: 'POL-IN-7781', product_id: 'IN-HEALTH-RETAIL', claimant_id: 'M-201', currency: 'INR', invoice_numbers: [],
  status: 'checked', source: 'structured', diagnosis: null, admission_date: null, discharge_date: null, proposed_settlement: null, ...c,
})

const claims: Claim[] = [
  mk({ claim_id: 'CLM-1001', claimant_name: 'Asha Verma', provider_id: 'P-APEX', provider_name: 'Apex Hospital', claim_type: 'inpatient',
    incident_date: '2026-08-11', admission_date: '2026-08-11', discharge_date: '2026-08-14', diagnosis: 'Appendicectomy', room_category: 'Private',
    requested_amount: 58400, proposed_settlement: 55000, invoice_numbers: ['INV-5521'] }),
  mk({ claim_id: 'CLM-1002', claimant_name: 'Rohan Iyer', claimant_id: 'M-202', provider_id: 'P-CITY', provider_name: 'City Care Clinic', claim_type: 'outpatient',
    incident_date: '2026-09-02', requested_amount: 4620, invoice_numbers: ['INV-7810'], diagnosis: 'Knee MRI', bank_account: 'ACC-90214471', contact_phone: '+91-98100-22011' }),
  mk({ claim_id: 'CLM-1003', claimant_name: 'Rohan Iyer', claimant_id: 'M-202', provider_id: 'P-CITY', provider_name: 'City Care Clinic', claim_type: 'outpatient',
    incident_date: '2026-09-04', requested_amount: 4600, invoice_numbers: ['INV-7814'], diagnosis: 'Knee MRI' }),
  mk({ claim_id: 'CLM-1004', claimant_name: 'Meera Nair', provider_id: 'P-PHYS', provider_name: 'Motion Physio Centre', claim_type: 'outpatient',
    incident_date: '2026-09-09', requested_amount: 1800, invoice_numbers: ['INV-3301'], diagnosis: 'Post-op physiotherapy' }),
  mk({ claim_id: 'CLM-1005', claimant_name: 'Vikram Shah', provider_id: 'P-CITY', provider_name: 'City Care Clinic', claim_type: 'inpatient',
    incident_date: '2026-09-15', admission_date: '2026-09-15', discharge_date: '2026-09-17', requested_amount: 91200, invoice_numbers: ['INV-7902'], diagnosis: 'Cataract surgery', bank_account: 'ACC-90214471', contact_phone: '+91-98100-22011' }),
  mk({ claim_id: 'CLM-1006', claimant_name: 'Sana Qureshi', provider_id: 'P-APEX', provider_name: 'Apex Hospital', claim_type: 'daycare',
    incident_date: '2026-09-21', requested_amount: 22000, invoice_numbers: [] }),
  mk({ claim_id: 'CLM-1007', claimant_name: 'Dev Malhotra', provider_id: 'P-GARAGE', provider_name: 'Prime Auto Works', claim_type: 'motor',
    incident_date: '2026-10-02', requested_amount: 37500, proposed_settlement: 37500, invoice_numbers: ['INV-9001'], policy_number: 'POL-MO-2210', product_id: 'IN-MOTOR' }),
  mk({ claim_id: 'CLM-1009', claimant_name: 'Neha Kapoor', claimant_id: 'M-310', provider_id: 'P-APEX', provider_name: 'Apex Hospital', claim_type: 'inpatient',
    incident_date: '2026-08-12', admission_date: '2026-08-11', discharge_date: '2026-08-14', diagnosis: 'Appendicectomy', requested_amount: 57400,
    invoice_numbers: ['INV-5521'], policy_number: 'POL-IN-9902' }),
  mk({ claim_id: 'CLM-1008', claimant_name: 'Isha Rao', provider_id: 'P-APEX', provider_name: 'Apex Hospital', claim_type: 'pharmacy',
    incident_date: '2026-10-12', requested_amount: 3150, invoice_numbers: ['INV-5710'], status: 'ingested' }),
]

const linesByClaim: Record<string, InvoiceLine[]> = {
  'CLM-1001': [
    line('CLM-1001', 'INV-5521', 1, 'Private room rent', 3, 5000, 'room', '2026-08-11', 'RM-PVT'),
    line('CLM-1001', 'INV-5521', 2, 'Appendicectomy (laparoscopic)', 1, 28000, 'surgery', '2026-08-12', 'SUR-APP'),
    line('CLM-1001', 'INV-5521', 3, 'Complete blood count', 1, 600, 'lab', '2026-08-11', 'LAB-CBC'),
    line('CLM-1001', 'INV-5521', 4, 'Complete blood count', 1, 600, 'lab', '2026-08-11', 'LAB-CBC'),
    line('CLM-1001', 'INV-5521', 5, 'Surgical gloves & mask', 1, 1250, 'medical', '2026-08-12'),
    line('CLM-1001', 'INV-5521', 6, 'Surgeon professional fee', 1, 9000, 'professional fees', '2026-08-12'),
    line('CLM-1001', 'INV-5521', 7, 'Medicines', 1, 2950, 'pharma', '2026-08-13'),
  ],
  'CLM-1002': [line('CLM-1002', 'INV-7810', 1, 'MRI knee', 1, 4620, 'radiology', '2026-09-02', 'RAD-MRI-K')],
  'CLM-1003': [line('CLM-1003', 'INV-7814', 1, 'MRI knee', 1, 4600, 'radiology', '2026-09-04', 'RAD-MRI-K')],
  'CLM-1004': [line('CLM-1004', 'INV-3301', 1, 'Physiotherapy session', 1, 900, 'services', '2026-09-09', 'PHY-01'),
    line('CLM-1004', 'INV-3301', 2, 'Physiotherapy session', 1, 900, 'services', '2026-09-10', 'PHY-01')],
  'CLM-1005': [line('CLM-1005', 'INV-7902', 1, 'Cataract surgery with IOL', 1, 78000, 'surgery', '2026-09-16', 'SUR-CAT'),
    line('CLM-1005', 'INV-7902', 2, 'Room rent', 2, 2800, 'room', '2026-09-15'), line('CLM-1005', 'INV-7902', 3, 'Medicines', 1, 7600, 'pharma', '2026-09-16')],
  'CLM-1007': [line('CLM-1007', 'INV-9001', 1, 'Front bumper (part)', 1, 18500, 'parts', '2026-10-03'), line('CLM-1007', 'INV-9001', 2, 'Paint & labour', 1, 19000, 'labour', '2026-10-04')],
  'CLM-1009': [line('CLM-1009', 'INV-5521', 1, 'Private room rent', 3, 5000, 'room', '2026-08-11', 'RM-PVT'),
    line('CLM-1009', 'INV-5521', 2, 'Appendicectomy (laparoscopic)', 1, 28000, 'surgery', '2026-08-12', 'SUR-APP'),
    line('CLM-1009', 'INV-5521', 3, 'Surgeon professional fee', 1, 9000, 'professional fees', '2026-08-12'),
    line('CLM-1009', 'INV-5521', 4, 'Medicines and consumables', 1, 5400, 'pharma', '2026-08-13')],
  'CLM-1008': [line('CLM-1008', 'INV-5710', 1, 'Paracetamol 650mg x 30', 3, 50, 'pharma', '2026-10-12'), line('CLM-1008', 'INV-5710', 2, 'Antibiotic course', 1, 3000, 'pharma', '2026-10-12')],
}

let seq = 0
const fnd = (claim: string, check: string, category: Finding['category'], severity: Severity, amount: number, kind: Finding['amount_kind'],
  rule_id: string, rule_text: string, calculation: string, reason: string, extra: Partial<Finding> = {}): Finding => ({
  finding_id: `${claim}:${check}:${++seq}`, claim_id: claim, check_id: check, category, severity, amount, amount_kind: kind, currency: 'INR',
  rule_id, rule_text, calculation, reason, line_ids: [], evidence: [], clause: null, related_claim_ids: [], status: 'open', reviewer_note: '', corrected_amount: null, ...extra,
})

const findings: Finding[] = [
  fnd('CLM-1001', 'ROOM_LIMIT_EXCEEDED', 'policy_rule', 'high', 6000, 'calculated', 'ROOM_RENT_LIMIT', 'Room rent is limited to ₹3,000 per day.',
    '(5,000 − 3,000) × 3 days = ₹6,000', 'Private room billed at ₹5,000/day for 3 days; the policy pays ₹3,000/day.', {
      line_ids: ['CLM-1001:INV-5521:1'],
      evidence: [{ source: 'invoice_line', ref: 'CLM-1001:INV-5521:1', quote: 'Private room rent  3 × 5,000 = 15,000' }, { source: 'policy', ref: 'POL-IN-7781', quote: 'room_rent_limit_per_day = 3,000' }],
      clause: { clause_id: '4.1', text: 'Room rent, boarding and nursing charges are payable up to ₹3,000 per day of hospitalisation.', score: 0.91 },
    }),
  fnd('CLM-1001', 'DUPLICATE_LINE', 'duplicate', 'medium', 600, 'calculated', 'DUP-LINE', 'The same charge may not be paid twice within a claim.',
    '1 duplicate × ₹600 = ₹600', 'Complete blood count appears twice on INV-5521 with the same date, code and amount.', {
      line_ids: ['CLM-1001:INV-5521:3', 'CLM-1001:INV-5521:4'],
      evidence: [{ source: 'invoice_line', ref: 'CLM-1001:INV-5521:3', quote: 'Complete blood count 11 Aug ₹600' }, { source: 'invoice_line', ref: 'CLM-1001:INV-5521:4', quote: 'Complete blood count 11 Aug ₹600' }],
    }),
  fnd('CLM-1001', 'NON_PAYABLE_ITEM', 'policy_rule', 'low', 1250, 'calculated', 'NON_PAYABLE_LIST', 'Consumables on the non-payable list are not reimbursed.',
    '₹1,250 (gloves & mask)', 'Gloves and masks are consumables on the product non-payable list.', {
      line_ids: ['CLM-1001:INV-5521:5'], evidence: [{ source: 'config', ref: 'IN-HEALTH-RETAIL', quote: 'non_payable_items: Gloves, Mask' }],
    }),
  fnd('CLM-1003', 'NEAR_DUPLICATE', 'duplicate', 'medium', 4600, 'suspected', 'NEAR-DUP', 'Same member, provider and service within 3 days and 2% of the amount is reviewed.',
    'Suspected: up to ₹4,600 if CLM-1003 repeats CLM-1002', 'Knee MRI billed by the same clinic two days later; invoice number and amount differ slightly (₹4,620 vs ₹4,600).', {
      related_claim_ids: ['CLM-1002'], line_ids: ['CLM-1003:INV-7814:1'],
      recommendation: 'clarify', recommendation_confidence: 0.72,
      recommendation_note: 'Same member, clinic and scan within two days; the invoice numbers differ by a few digits. No second referral is on file, so ask the clinic whether this is a re-bill of INV-7810.',
      evidence: [{ source: 'claim', ref: 'CLM-1002', quote: 'MRI knee 02 Sep ₹4,620 INV-7810' }, { source: 'claim', ref: 'CLM-1003', quote: 'MRI knee 04 Sep ₹4,600 INV-7814' }],
    }),
  fnd('CLM-1005', 'SUBLIMIT_EXCEEDED', 'policy_rule', 'high', 38000, 'calculated', 'SUBLIMIT_CATARACT', 'Cataract surgery is capped at ₹40,000 per claim.',
    '78,000 − 40,000 = ₹38,000', 'Cataract surgery with IOL billed at ₹78,000; the sub-limit is ₹40,000.', {
      line_ids: ['CLM-1005:INV-7902:1'], clause: { clause_id: '4.3', text: 'Cataract surgery including lens is payable up to ₹40,000 per eye.', score: 0.88 },
      evidence: [{ source: 'invoice_line', ref: 'CLM-1005:INV-7902:1', quote: 'Cataract surgery with IOL ₹78,000' }],
    }),
  fnd('CLM-1005', 'PROVIDER_PRICE_OUTLIER', 'pattern', 'medium', 22000, 'suspected', 'PEER_BENCHMARK', 'Unit price above 2.5σ of peer providers for the same code.',
    'Suspected: (78,000 − peer median 56,000) = ₹22,000', 'City Care bills cataract surgery 39% above the peer median across 14 comparable claims. This is a pattern for review, not a conclusion of fraud.', {
      line_ids: ['CLM-1005:INV-7902:1'], evidence: [{ source: 'history', ref: 'peer SUR-CAT', quote: 'median ₹56,000, σ ₹6,100, n=14' }],
      recommendation: 'confirm', recommendation_confidence: 0.64,
      recommendation_note: 'Peer prices for SUR-CAT range from ₹48,000 to ₹66,000 across 14 lines; this charge is above the highest. The lens is included in the price, which explains part of the gap.',
    }),
  fnd('CLM-1005', 'RELATED_PARTY_PATTERN', 'pattern', 'medium', 0, 'suspected', 'SHARED_BANK', 'Claims sharing a bank account across different claimants are reviewed.',
    'No amount can be determined', 'The payee bank account matches CLM-1002 (a different claimant at the same provider).', {
      recommendation: 'clarify', recommendation_confidence: 0.8,
      recommendation_note: 'The payee bank account and phone match CLM-1002, a different member at the same clinic. Request proof of relationship before paying.',
      related_claim_ids: ['CLM-1002'], evidence: [{ source: 'claim', ref: 'CLM-1005', quote: 'bank_account …4471' }, { source: 'claim', ref: 'CLM-1002', quote: 'bank_account …4471' }],
    }),
  fnd('CLM-1009', 'DUPLICATE_CLAIM', 'duplicate', 'high', 57400, 'calculated', 'DUP-CLAIM-01', 'The same invoice cannot be claimed twice.',
    'invoice INV-5521 also on claim CLM-1001; duplicate = requested amount',
    'Invoice INV-5521 from Apex Hospital is attached to this claim and to CLM-1001, which is under a different policy (POL-IN-7781).', {
      related_claim_ids: ['CLM-1001'],
      evidence: [{ source: 'claim', ref: 'CLM-1001', quote: 'invoices INV-5521 requested ₹58,400, policy POL-IN-7781' }, { source: 'claim', ref: 'CLM-1009', quote: 'invoices INV-5521 requested ₹57,400, policy POL-IN-9902' }],
    }),
  fnd('CLM-1006', 'MISSING_EVIDENCE', 'evidence', 'low', 0, 'suspected', 'REQUIRED_DOCS', 'A daycare claim needs an itemised bill and a discharge summary.',
    'Cannot be calculated without the invoice', 'No invoice lines or bill were supplied, so no leakage assessment is possible. Ask the provider for the itemised bill.', {
      evidence: [{ source: 'config', ref: 'IN-HEALTH-RETAIL', quote: 'required: itemized_final_hospital_bill' }],
    }),
  fnd('CLM-1007', 'SETTLEMENT_MISMATCH', 'settlement', 'high', 3750, 'calculated', 'SETTLE-RECALC', 'Payable = lines − deductions − deductible − co-pay.',
    'Proposed 37,500 − recalculated 33,750 = ₹3,750', 'The handler proposed the full requested amount; the 10% co-pay and ₹0 deductible were not applied.', {
      evidence: [{ source: 'claim', ref: 'CLM-1007', quote: 'proposed_settlement = 37,500' }],
    }),
]

const claimsByStatus: Record<string, string> = {}
claims.forEach((c) => { claimsByStatus[c.claim_id] = c.status })

// ---- derived views ----------------------------------------------------------------------------------------------

const effective = (f: Finding): number =>
  f.status === 'dismissed' ? 0 : f.status === 'corrected' && f.corrected_amount != null ? f.corrected_amount : f.amount_kind === 'calculated' ? f.amount : 0

const SEV: Record<Severity, number> = { low: 1, medium: 2, high: 3 }

function summarise(claim: Claim): ClaimSummary {
  const fs = findings.filter((f) => f.claim_id === claim.claim_id)
  const live = fs.filter((f) => f.status !== 'dismissed')
  const top = live.reduce<Severity | null>((acc, f) => (acc === null || SEV[f.severity] > SEV[acc] ? f.severity : acc), null)
  return {
    claim_id: claim.claim_id, claimant: claim.claimant_name!.split(' ').map((p) => p[0]).join(''), claimant_id: claim.claimant_id,
    provider: claim.provider_name ?? claim.provider_id, provider_id: claim.provider_id, claim_type: claim.claim_type, product_id: claim.product_id,
    incident_date: claim.incident_date, requested_amount: claim.requested_amount, currency: claim.currency,
    leakage_calculated: live.reduce((s, f) => s + effective(f), 0),
    leakage_suspected: live.filter((f) => f.amount_kind === 'suspected' && f.status !== 'corrected').reduce((s, f) => s + f.amount, 0),
    severity: top, findings: fs.length, open_findings: fs.filter((f) => f.status === 'open').length, status: claimsByStatus[claim.claim_id], updated_at: iso(),
  }
}

function passes(claim: Claim, p: ClaimFilters): boolean {
  const num = (v: unknown) => (v === undefined || v === '' ? undefined : Number(v))
  if (p.type && claim.claim_type !== p.type) return false
  if (p.provider && p.provider !== claim.provider_id && p.provider !== claim.provider_name) return false
  if (p.status && claimsByStatus[claim.claim_id] !== p.status) return false
  const min = num(p.min_amount), max = num(p.max_amount)
  if (min !== undefined && claim.requested_amount < min) return false
  if (max !== undefined && claim.requested_amount > max) return false
  if (p.from && claim.incident_date < p.from) return false
  if (p.to && claim.incident_date > p.to) return false
  if (p.category && !findings.some((f) => f.claim_id === claim.claim_id && f.category === p.category && f.status !== 'dismissed')) return false
  return true
}

function settle(claim: Claim): Settlement | null {
  const lines = linesByClaim[claim.claim_id]
  if (!lines || claimsByStatus[claim.claim_id] === 'ingested') return null
  const fs = findings.filter((f) => f.claim_id === claim.claim_id && f.check_id !== 'SETTLEMENT_MISMATCH')
  const linesTotal = lines.reduce((s, l) => s + l.amount, 0)
  const deductions = fs.filter((f) => effective(f) > 0).map((f) => ({ finding_id: f.finding_id, check_id: f.check_id, amount: effective(f), reason: f.reason.slice(0, 80) }))
  const after = linesTotal - deductions.reduce((s, d) => s + d.amount, 0)
  const ded = claim.claim_type === 'motor' ? 0 : POLICY.deductible.amount
  const copayPct = claim.claim_type === 'inpatient' ? POLICY.copay.inpatient_pct : claim.claim_type === 'pharmacy' ? POLICY.copay.pharmacy_pct : claim.claim_type === 'motor' ? 10 : POLICY.copay.outpatient_pct
  const copay = Math.round(((after - ded) * copayPct) / 100)
  const payable = Math.max(0, after - ded - copay)
  const proposed = claim.proposed_settlement ?? null
  return {
    claim_id: claim.claim_id, currency: claim.currency, requested_amount: claim.requested_amount, lines_total: linesTotal, deductions, after_deductions: after,
    deductible_amount: ded, copay_pct: copayPct, copay_amount: copay, benefit_cap_applied: 0, payable, patient_pays: claim.requested_amount - payable,
    proposed_settlement: proposed, difference: proposed === null ? null : proposed - payable,
    steps: [`Invoice lines total ${linesTotal.toLocaleString('en-IN')}`, ...deductions.map((d) => `− ${d.check_id} ${d.amount.toLocaleString('en-IN')}`),
      `− Deductible ${ded.toLocaleString('en-IN')}`, `− Co-pay ${copayPct}% = ${copay.toLocaleString('en-IN')}`, `= Payable ${payable.toLocaleString('en-IN')}`],
  }
}

function classificationFor(claimId: string): ClassificationRow[] {
  if (claimId !== 'CLM-1006') return []
  return [
    { document_id: 'DOC-1', document_name: 'scan_001.pdf', page_id: 'DOC-1:1', page: 1, predicted_type: 'claim_form', confidence: 0.97, confirmed_type: null, predicted_by: 'kimi-k2.5' },
    { document_id: 'DOC-1', document_name: 'scan_001.pdf', page_id: 'DOC-1:2', page: 2, predicted_type: 'other_documents', confidence: 0.54, confirmed_type: null, predicted_by: 'kimi-k2.5' },
  ]
}

const DOC1 = { document_id: 'DOC-2', document_name: 'CLM-1001_bill.pdf' }
const FACTS: Record<string, NonNullable<ClaimDetail['document_facts']>> = {
  'CLM-1001': [
    { field: 'claimant_name', value: 'Asha Verma', ...DOC1, page: 1 }, { field: 'policy_number', value: 'POL-IN-7781', ...DOC1, page: 1 },
    { field: 'invoice_no', value: 'INV-5521', ...DOC1, page: 1 }, { field: 'admission_date', value: '2026-08-11', ...DOC1, page: 1 },
    { field: 'discharge_date', value: '2026-08-15', ...DOC1, page: 1 }, { field: 'net_payable', value: '57,650', ...DOC1, page: 2 },
  ],
}
const DOC_LINES: Record<string, NonNullable<ClaimDetail['document_lines']>> = {
  'CLM-1001': [
    { description: 'Private room rent', amount: 15000, service_date: '2026-08-11', ...DOC1, page: 1 },
    { description: 'Appendicectomy (laparoscopic)', amount: 28000, service_date: '2026-08-12', ...DOC1, page: 1 },
    { description: 'Complete blood count', amount: 600, service_date: '2026-08-11', ...DOC1, page: 1 },
    { description: 'Surgical gloves & mask', amount: 1250, service_date: '2026-08-12', ...DOC1, page: 2 },
    { description: 'Surgeon professional fee', amount: 9500, service_date: '2026-08-12', ...DOC1, page: 2 },
    { description: 'Medicines', amount: 2950, service_date: '2026-08-13', ...DOC1, page: 2 },
  ],
}
const notes: Record<string, CaseNote[]> = {}

function detail(id: string): ClaimDetail {
  const claim = claims.find((c) => c.claim_id === id)
  if (!claim) throw Object.assign(new Error(`claim ${id} not found`), { status: 404 })
  const fs = findings.filter((f) => f.claim_id === id)
  const summary = summarise(claim)
  const classification = classificationFor(id)
  const checked = claimsByStatus[id] !== 'ingested'
  return {
    claim: { ...claim, status: claimsByStatus[id] }, policy: claim.product_id === 'IN-MOTOR' ? null : POLICY, product: PRODUCT, lines: linesByClaim[id] ?? [],
    documents: classification.length ? [{ id: 'DOC-1', name: 'scan_001.pdf', type: null, pages: 2, mime: 'application/pdf', uploaded_at: iso() }]
      : id === 'CLM-1001' ? [{ id: 'DOC-2', name: 'CLM-1001_bill.pdf', type: 'itemized_final_hospital_bill', pages: 2, mime: 'application/pdf', uploaded_at: iso() }] : [],
    classification, findings: [...fs].sort((a, b) => SEV[b.severity] - SEV[a.severity]), settlement: settle(claim),
    audit: audits.filter((a) => a.claim_id === id),
    run: checked ? { run_id: `RUN-${id}`, claim_id: id, status: 'completed', steps: ['load_master', 'run_checks', 'assess', 'settle', 'done'].map((name) => ({ name, status: 'completed', started: iso(), ended: iso() })), cost_usd: 0, paused_at: null } : null,
    summary, reconciled: id === 'CLM-1001' ? false : linesByClaim[id] ? true : null,
    printed_total: id === 'CLM-1001' ? 57650 : linesByClaim[id]?.reduce((s, l) => s + l.amount, 0) ?? null,
    document_facts: FACTS[id], document_lines: DOC_LINES[id],
  }
}

const audits: AuditRow[] = claims.filter((c) => c.status === 'checked').map((c, i) => ({
  audit_id: `AUD-${i}`, ts: iso(), actor: 'system', action: 'run', claim_id: c.claim_id, details: { run_id: `RUN-${c.claim_id}` },
}))

function dashboard(p: ClaimFilters): Dashboard {
  const rows = claims.filter((c) => passes(c, p))
  const cat: Record<string, Dashboard['by_category'][number]> = {}
  const chk: Record<string, Dashboard['by_check'][number]> = {}
  const sev: Record<string, Dashboard['by_severity'][number]> = {}
  const prov: Record<string, Dashboard['by_provider'][number]> = {}
  let calc = 0, susp = 0, flagged = 0, awaiting = 0
  rows.forEach((c) => {
    const fs = findings.filter((f) => f.claim_id === c.claim_id)
    const live = fs.filter((f) => f.status !== 'dismissed')
    const s = summarise(c)
    calc += s.leakage_calculated; susp += s.leakage_suspected
    if (live.length) flagged++
    if (fs.some((f) => f.status === 'open')) awaiting++
    const pr = (prov[c.provider_id] ??= { provider_id: c.provider_id, provider_name: c.provider_name ?? c.provider_id, claims: 0, flagged: 0, leakage_calculated: 0, leakage_suspected: 0 })
    pr.claims++; pr.flagged += live.length ? 1 : 0; pr.leakage_calculated += s.leakage_calculated; pr.leakage_suspected += s.leakage_suspected
    live.forEach((f) => {
      const cal = effective(f), su = f.amount_kind === 'suspected' && f.status !== 'corrected' ? f.amount : 0
      const a = (cat[f.category] ??= { category: f.category, count: 0, amount_calculated: 0, amount_suspected: 0 })
      const b = (chk[f.check_id] ??= { check_id: f.check_id, count: 0, amount_calculated: 0, amount_suspected: 0 })
      ;[a, b].forEach((e) => { e.count++; e.amount_calculated += cal; e.amount_suspected += su })
      const sv = (sev[f.severity] ??= { severity: f.severity, count: 0, amount: 0 })
      sv.count++; sv.amount += cal + su
    })
  })
  const processed = rows.filter((c) => claimsByStatus[c.claim_id] !== 'ingested').length
  return {
    claims: rows.length, processed, flagged, leakage_calculated: calc, leakage_suspected: susp, awaiting_review: awaiting,
    by_category: Object.values(cat).sort((a, b) => b.count - a.count), by_check: Object.values(chk).sort((a, b) => b.count - a.count),
    by_severity: Object.values(sev).sort((a, b) => SEV[b.severity] - SEV[a.severity]),
    by_provider: Object.values(prov).sort((a, b) => b.leakage_calculated + b.leakage_suspected - a.leakage_calculated - a.leakage_suspected),
  }
}

const EVAL: EvalSummary = {
  available: true, planted: 24, must_not_flag: 6, overall: { tp: 20, fp: 3, fn: 4, precision: 0.87, recall: 0.833 },
  amount_planted: 412300, amount_recovered: 351900, look_alikes_wrongly_flagged: [{ claim_id: 'CLM-1004', check_id: 'DUPLICATE_LINE', note: 'legitimate look-alike was flagged' }],
  by_check: { DUPLICATE_LINE: { tp: 5, fp: 0, fn: 0, precision: 1, recall: 1 }, ROOM_LIMIT_EXCEEDED: { tp: 4, fp: 0, fn: 1, precision: 1, recall: 0.8 }, NEAR_DUPLICATE: { tp: 3, fp: 2, fn: 1, precision: 0.6, recall: 0.75 } },
}

let product = PRODUCT

// ---- router -----------------------------------------------------------------------------------------------------

export async function mockRequest<T>(method: string, path: string, params: Record<string, string | number | undefined | null>, body?: unknown, form?: FormData): Promise<T> {
  await delay()
  const filters = params as ClaimFilters
  const bodyObj = (body ?? {}) as Record<string, unknown>
  let m: RegExpMatchArray | null

  if (path === '/health') return { status: 'ok', store: 'mock', ts: iso() } as T
  if (path === '/claims' && method === 'GET') return claims.filter((c) => passes(c, filters)).map(summarise) as T
  if (path === '/dashboard') return dashboard(filters) as T
  if (path === '/eval/summary') return EVAL as T
  if (path === '/config' && method === 'GET') return [product] as T
  if ((m = path.match(/^\/config\/(.+)$/))) {
    if (method === 'PUT') { product = body as ProductConfig; return product as T }
    return product as T
  }
  if (path === '/audit') return audits.filter((a) => !params.claim_id || a.claim_id === params.claim_id) as T

  if (path === '/ingest') {
    const names = form ? form.getAll('files').map((f) => (f as File).name) : []
    const result: IngestResult = {
      batch_id: `B-${Date.now()}`, counts: { claims: 8, invoice_lines: 22, policies: 2, history: 5 }, claims_created: 0, claims_affected: claims.map((c) => c.claim_id), documents: [],
      validation: [
        { file: names[0] ?? 'claims.csv', row: 14, field: 'incident_date', problem: "'31/02/2026' is not a valid date", accepted: false },
        { file: names[0] ?? 'claims.csv', row: 22, field: 'requested_amount', problem: 'negative amount (−1200)', accepted: false },
        { file: names[0] ?? 'claims.csv', row: 31, field: 'provider_name', problem: 'blank; provider_id used instead', accepted: true },
      ],
    }
    return result as T
  }

  if ((m = path.match(/^\/claims\/([^/]+)\/notes$/))) {
    const id = decodeURIComponent(m[1])
    if (method === 'POST') {
      const n: CaseNote = { note_id: `N-${Date.now()}`, claim_id: id, author: String(bodyObj.author ?? 'analyst'), text: String(bodyObj.text ?? ''), ts: iso() }
      notes[id] = [...(notes[id] ?? []), n]
      audits.push({ audit_id: `AUD-${audits.length}`, ts: iso(), actor: n.author, action: 'note_added', claim_id: id, details: { note: n.text } })
      return n as T
    }
    return (notes[id] ?? []) as T
  }
  if ((m = path.match(/^\/claims\/([^/]+)\/run$/))) {
    const id = decodeURIComponent(m[1])
    if (method === 'POST') { claimsByStatus[id] = 'checked'; return { run_id: `RUN-${id}`, claim_id: id, status: 'queued' } as T }
    const run: Run = { run_id: `RUN-${id}`, claim_id: id, status: 'completed', steps: [], cost_usd: 0, paused_at: null }
    return run as T
  }
  if ((m = path.match(/^\/claims\/([^/]+)\/classification\/confirm$/))) {
    const id = decodeURIComponent(m[1])
    return { claim_id: id, classification: classificationFor(id), run_id: null } as T
  }
  if ((m = path.match(/^\/claims\/([^/]+)\/findings\/(.+)\/review$/))) {
    const claimId = decodeURIComponent(m[1]), fid = decodeURIComponent(m[2])
    const f = findings.find((x) => x.finding_id === fid)
    if (!f) throw Object.assign(new Error('finding not found'), { status: 404 })
    const action = bodyObj.action as ReviewAction
    f.status = ({ confirm: 'confirmed', correct: 'corrected', dismiss: 'dismissed', clarify: 'clarification_requested' } as const)[action]
    f.reviewer_note = String(bodyObj.note ?? '')
    f.corrected_amount = action === 'correct' ? Number(bodyObj.amount) : null
    audits.push({ audit_id: `AUD-${audits.length}`, ts: iso(), actor: 'reviewer', action: `review_${action}`, claim_id: claimId, details: { finding_id: fid, note: f.reviewer_note, amount: bodyObj.amount ?? null } })
    const d = detail(claimId)
    return { claim_id: claimId, run_id: null, findings: d.findings, settlement: d.settlement, summary: d.summary } as T
  }
  if ((m = path.match(/^\/claims\/([^/]+)$/))) return detail(decodeURIComponent(m[1])) as T

  throw Object.assign(new Error(`mock: no route for ${method} ${path}`), { status: 404 })
}
