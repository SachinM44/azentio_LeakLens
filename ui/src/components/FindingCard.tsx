import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Dropdown, Input, InputNumber, Modal, Progress, Radio, Select, Tag } from 'antd'
import { ArrowRight, Bot, Check, ChevronDown, Layers, Pencil, SearchCheck, ShieldAlert, ThumbsUp, X } from 'lucide-react'
import type { ClaimDetail, Finding } from '../api/types'
import { buildCorrection } from '../lib/analysis'
import { FALSE_POSITIVE_REASONS, currentDecision, type DecisionKind } from '../lib/decisions'
import { CATEGORY_COLOR, SEVERITY_COLOR, checkLabel, money, pct } from '../lib/format'
import { IconBubble } from './ui'
import { AmountKindBadge, SeverityBadge, StatusTag } from './Badges'

export interface DecisionInput { reason?: string; text?: string; amount?: number }

interface Props {
  finding: Finding
  detail: ClaimDetail
  busy: boolean
  onDecide: (kind: DecisionKind, input: DecisionInput) => void
  onLineClick?: (lineId: string) => void
  onEvidenceClick?: (source: string, ref: string) => void
}

const SOURCE_COLOR: Record<string, string> = {
  claim: 'blue', invoice_line: 'geekblue', policy: 'purple', history: 'gold', document: 'cyan', config: 'default',
}

const RECO_STYLE: Record<string, { color: string; label: string }> = {
  confirm: { color: 'red', label: 'Confirm as leakage' },
  dismiss: { color: 'default', label: 'Dismiss as false positive' },
  clarify: { color: 'orange', label: 'Ask for clarification' },
}

type Dialog = null | 'false_positive' | 'request_evidence' | 'escalate' | 'override'

export default function FindingCard({ finding: f, detail, busy, onDecide, onLineClick, onEvidenceClick }: Props) {
  const [dialog, setDialog] = useState<Dialog>(null)
  const [reason, setReason] = useState<string | undefined>()
  const [text, setText] = useState('')
  const [target, setTarget] = useState<'escalate_senior' | 'escalate_siu'>('escalate_senior')
  const [amount, setAmount] = useState<number | null>(f.corrected_amount ?? f.amount)

  const correction = buildCorrection(f, detail)
  const decision = currentDecision(f)
  const isEvidenceGap = f.category === 'evidence'
  const dismissed = f.status === 'dismissed'
  const overridden = decision?.decision === 'override_correction' && f.corrected_amount != null
  const reco = f.recommendation ? RECO_STYLE[f.recommendation] : undefined

  const close = () => { setDialog(null); setReason(undefined); setText('') }
  const submit = (kind: DecisionKind) => {
    onDecide(kind, { reason, text, amount: kind === 'override_correction' ? amount ?? 0 : undefined })
    close()
  }

  const decisionMenu = [
    { key: 'false_positive', icon: <X size={14} />, label: 'Mark as false positive…', onClick: () => setDialog('false_positive') },
    { key: 'request_evidence', icon: <SearchCheck size={14} />, label: 'Request additional evidence…', onClick: () => setDialog('request_evidence') },
    { key: 'escalate', icon: <ShieldAlert size={14} />, label: 'Escalate…', onClick: () => setDialog('escalate') },
  ]

  return (
    <div data-tour="finding" className={`card rise relative overflow-hidden p-5 pl-6 ${dismissed ? 'opacity-70' : ''} ${isEvidenceGap ? '!border-amber-300' : ''}`}>
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ background: isEvidenceGap ? '#ffc107' : SEVERITY_COLOR[f.severity] }} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <IconBubble color={CATEGORY_COLOR[f.category]} size={42}><Layers size={20} /></IconBubble>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[16px] font-semibold">{checkLabel(f.check_id)}</span>
              <SeverityBadge severity={f.severity} />
              {decision?.meta ? <Tag color={decision.meta.color} className="!m-0">{decision.meta.short}</Tag> : <StatusTag status={f.status} />}
            </div>
            <div className="mono mt-0.5 text-[12px] text-slate-400">{f.finding_id}</div>
          </div>
        </div>
        <div className="text-right">
          {f.amount > 0 ? (
            <>
              <div className="num text-[22px] font-semibold leading-tight">{money(overridden ? f.corrected_amount : f.amount, f.currency)}</div>
              {overridden && <div className="num text-[12px] text-slate-400 line-through">{money(f.amount, f.currency)}</div>}
              <div className="mt-1"><AmountKindBadge kind={f.amount_kind} /></div>
            </>
          ) : (
            <Tag color={isEvidenceGap ? 'orange' : 'default'} className="!m-0">{isEvidenceGap ? 'Needs clarification' : 'No amount determinable'}</Tag>
          )}
        </div>
      </div>

      <p className="mb-2 mt-3 text-[14px] leading-relaxed">{f.reason}</p>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl bg-slate-50 p-3.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Rule applied</div>
          <div className="mt-1 text-[13px]"><span className="mono rounded bg-white px-1.5 py-0.5 text-[12px] ring-1 ring-slate-200">{f.rule_id}</span></div>
          <div className="mt-1.5 text-[13px] text-slate-700">{f.rule_text}</div>
        </div>
        <div className="rounded-xl bg-slate-50 p-3.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {f.amount_kind === 'calculated' ? 'Calculation' : 'Estimate basis (not a confirmed amount)'}
          </div>
          <div className="mono mt-1.5 whitespace-pre-wrap text-[13px] text-slate-800">{f.calculation || '—'}</div>
        </div>
      </div>

      {/* Level 2: AI recommendation and the specific correction it implies */}
      {(reco || correction) && (
        <div className="mt-3 rounded-2xl border border-emerald-200 bg-gradient-to-br from-mint/70 to-white p-4">
          {reco && (
            <div className="flex flex-wrap items-start gap-2.5">
              <IconBubble size={30}><Bot size={16} /></IconBubble>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="font-semibold">Investigator suggests</span>
                  <Tag color={reco.color} className="!m-0">{reco.label}</Tag>
                  {f.recommendation_confidence != null && <span className="muted text-[12px]">{pct(f.recommendation_confidence)} confidence</span>}
                </div>
                {f.recommendation_note && <div className="mt-1 text-[13px] text-slate-700">{f.recommendation_note}</div>}
                <div className="muted mt-1 text-[11.5px]">Advisory only. It never changes an amount or a status.</div>
              </div>
            </div>
          )}
          {correction && (
            <div className={reco ? 'mt-3 border-t border-emerald-100 pt-3' : ''}>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Recommended correction{correction.conditional ? ' (applies only if confirmed)' : ''}
              </div>
              <div className="mt-1 text-[14px] font-semibold">{correction.headline}</div>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <div className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200">
                  <div className="muted text-[11px]">Original</div><div className="num text-[16px] font-semibold">{money(correction.original, f.currency)}</div>
                </div>
                <ArrowRight size={18} className="text-slate-400" />
                <div className="rounded-xl bg-white px-3 py-2 ring-2 ring-accent">
                  <div className="muted text-[11px]">Corrected</div><div className="num text-[16px] font-semibold text-emerald-700">{money(correction.corrected, f.currency)}</div>
                </div>
                <div className="muted text-[12px]">based on {correction.basis}</div>
              </div>
              <div className="mono mt-2 whitespace-pre-wrap text-[12.5px] text-slate-700">{correction.calculation}</div>
              <div className="mt-1.5 text-[12.5px] text-slate-600"><b>Supported by</b> <span className="mono">{correction.ruleId}</span>: {correction.ruleText}</div>
              {correction.clause && <div className="mt-1 text-[12px] italic text-slate-500">{correction.clause}</div>}
              {overridden && (
                <div className="mt-2 rounded-lg bg-amber-50 p-2 text-[12.5px] text-amber-900">
                  Overridden by {decision?.by ?? 'the analyst'}: corrected to <b>{money(f.corrected_amount, f.currency)}</b>. The original recommendation
                  ({money(f.amount, f.currency)}) is kept on record{decision?.reason ? `. Reason: ${decision.reason}` : ''}.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {f.clause && (
        <div className="mt-3 rounded-lg border-l-4 border-accent bg-mint/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-semibold text-brand">Policy clause {f.clause.clause_id}</span>
            <span className="flex items-center gap-2 text-[11px] text-slate-500">
              match <Progress percent={Math.round(f.clause.score * 100)} size="small" className="!m-0 w-24" />
            </span>
          </div>
          <div className="mt-1 text-[13px] italic text-slate-700">“{f.clause.text}”</div>
        </div>
      )}

      {(f.evidence.length > 0 || f.line_ids.length > 0 || f.related_claim_ids.length > 0) && (
        <div className="mt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Supporting evidence · click to inspect</div>
          <ul className="m-0 mt-1.5 list-none space-y-1 p-0">
            {f.evidence.map((e, i) => (
              <li key={i}>
                <button type="button" onClick={() => onEvidenceClick?.(e.source, e.ref)}
                  className="flex w-full cursor-pointer flex-wrap items-baseline gap-2 rounded-lg border-0 bg-transparent p-1.5 text-left text-[13px] hover:bg-slate-50">
                  <Tag color={SOURCE_COLOR[e.source] ?? 'default'} className="!m-0">{e.source.replace('_', ' ')}</Tag>
                  <span className="mono text-[12px] text-slate-500">{e.ref}</span>
                  {e.quote && <span className="text-slate-800">“{e.quote}”</span>}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
            {f.line_ids.map((id) => (
              <button key={id} type="button" onClick={() => onLineClick?.(id)}
                className="mono cursor-pointer rounded border border-slate-200 bg-white px-1.5 py-0.5 hover:border-brand hover:text-brand">
                line {id.split(':').slice(1).join(' #')}
              </button>
            ))}
            {f.related_claim_ids.map((id) => (
              <Link key={id} to={`/claims/${encodeURIComponent(id)}`} className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-amber-800">
                related claim {id}
              </Link>
            ))}
          </div>
        </div>
      )}

      {decision && (
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <Tag color={decision.meta?.color} className="!m-0">{decision.meta?.label}</Tag>
            {decision.by && <span className="muted">by {decision.by}</span>}
          </div>
          {decision.reason && <div className="mt-1"><b>Reason:</b> {decision.reason}</div>}
          {decision.text && <div className="mt-0.5">{decision.text}</div>}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <Button type="primary" icon={<Check size={14} />} loading={busy} disabled={decision?.decision === 'confirm_discrepancy'}
          onClick={() => onDecide('confirm_discrepancy', {})}>Confirm discrepancy</Button>
        {correction && (
          <Button icon={<ThumbsUp size={14} />} loading={busy} disabled={decision?.decision === 'accept_correction'}
            onClick={() => onDecide('accept_correction', {})}>Accept recommended correction</Button>
        )}
        {correction && !isEvidenceGap && (
          <Button icon={<Pencil size={14} />} onClick={() => setDialog('override')}>Override…</Button>
        )}
        <Dropdown trigger={['click']} menu={{ items: decisionMenu }}>
          <Button>More decisions <ChevronDown size={14} className="ml-1 inline" /></Button>
        </Dropdown>
      </div>

      {/* False positive */}
      <Modal open={dialog === 'false_positive'} onCancel={close} title="Mark as false positive" okText="Record decision"
        okButtonProps={{ disabled: !reason }} onOk={() => submit('false_positive')}>
        <p className="muted text-[13px]">A reason is required, and it is kept in the audit trail.</p>
        <Select className="!mb-3 w-full" placeholder="Choose a reason" value={reason} onChange={setReason}
          options={FALSE_POSITIVE_REASONS.map((r) => ({ value: r, label: r }))} />
        <Input.TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add detail (optional)" />
      </Modal>

      {/* Request evidence */}
      <Modal open={dialog === 'request_evidence'} onCancel={close} title="Request additional evidence" okText="Send request"
        okButtonProps={{ disabled: !reason }} onOk={() => submit('request_evidence')}>
        <p className="muted text-[13px]">Say what is needed and from whom. The finding stays open until it arrives.</p>
        <Select className="!mb-3 w-full" placeholder="What do you need?" value={reason} onChange={setReason}
          options={['Itemised bill', 'Discharge summary', 'Prescription or referral', 'Proof of relationship', 'Provider confirmation', 'Other'].map((r) => ({ value: r, label: r }))} />
        <Input.TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Message to the provider or member" />
      </Modal>

      {/* Escalate */}
      <Modal open={dialog === 'escalate'} onCancel={close} title="Escalate this finding" okText="Escalate"
        okButtonProps={{ disabled: !reason }} onOk={() => submit(target)}>
        <Radio.Group className="!mb-3 flex flex-col gap-2" value={target} onChange={(e) => setTarget(e.target.value)}>
          <Radio value="escalate_senior"><b>Senior Claims Reviewer</b><div className="muted text-[12px]">Needs a second opinion or higher authority</div></Radio>
          <Radio value="escalate_siu"><b>Special Investigation Unit</b><div className="muted text-[12px]">Pattern suggests deliberate or organised leakage</div></Radio>
        </Radio.Group>
        <Input value={reason ?? ''} onChange={(e) => setReason(e.target.value)} className="!mb-2" placeholder="Why is this being escalated? (required)" />
        <Input.TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Notes for the reviewer" />
      </Modal>

      {/* Override */}
      <Modal open={dialog === 'override'} onCancel={close} title="Override the recommended correction" okText="Save override"
        okButtonProps={{ disabled: !reason || amount === null }} onOk={() => submit('override_correction')}>
        <p className="muted text-[13px]">
          The original recommendation ({money(f.amount, f.currency)}) stays on record. Your amount replaces it in the settlement, and the reason is audited.
        </p>
        <InputNumber min={0} className="!mb-3 !w-full" value={amount} onChange={setAmount} prefix={f.currency} placeholder="Your amount" />
        <Input value={reason ?? ''} onChange={(e) => setReason(e.target.value)} className="!mb-2" placeholder="Reason for the override (required)" />
        <Input.TextArea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Notes (optional)" />
      </Modal>
    </div>
  )
}

