import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Input, InputNumber, Modal, Popover, Progress, Radio, Space, Tag } from 'antd'
import { ArrowRight, Bot, Check, CheckCheck, Layers, MessageCircleQuestion, Pencil, ShieldAlert, X } from 'lucide-react'
import type { EscalateTo, Finding, ReviewBody } from '../api/types'
import { CATEGORY_COLOR, SEVERITY_COLOR, checkLabel, fmtDateTime, money, titleCase } from '../lib/format'
import { IconBubble } from './ui'
import { AmountKindBadge, SeverityBadge, StatusTag } from './Badges'

interface Props {
  finding: Finding
  busy: boolean
  onReview: (body: ReviewBody) => void
  onLineClick?: (lineId: string) => void
}

const SOURCE_COLOR: Record<string, string> = {
  claim: 'blue', invoice_line: 'geekblue', policy: 'purple', history: 'gold', document: 'cyan', config: 'default',
}

const ESCALATE_LABEL: Record<string, string> = { senior_reviewer: 'Senior claims reviewer', siu: 'Special Investigation Unit' }
const RECOMMEND_LABEL: Record<string, string> = { confirm: 'Confirm the discrepancy', dismiss: 'Treat as a false positive', clarify: 'Request evidence' }

export default function FindingCard({ finding: f, busy, onReview, onLineClick }: Props) {
  const [note, setNote] = useState('')
  const [amount, setAmount] = useState<number | null>(f.corrected_amount ?? (f.amount_kind === 'calculated' ? f.amount : null))
  const [correctOpen, setCorrectOpen] = useState(false)
  const [correctReason, setCorrectReason] = useState('')
  const [fpOpen, setFpOpen] = useState(false)
  const [fpReason, setFpReason] = useState('')
  const [escOpen, setEscOpen] = useState(false)
  const [escTo, setEscTo] = useState<EscalateTo>('senior_reviewer')
  const [escNote, setEscNote] = useState('')
  const isEvidenceGap = f.category === 'evidence'
  const decided = f.status !== 'open' && f.status !== 'auto_applied'
  const dismissed = f.status === 'dismissed'
  const hasAmount = f.amount > 0
  const shownAmount = f.status === 'corrected' && f.corrected_amount != null ? f.corrected_amount : f.amount
  const c = f.correction
  const o = f.original
  const history = f.decision_history ?? []
  // The override is visible when the decision moved away from what the system first recommended.
  const overridden = !!o && (o.amount !== shownAmount || f.status === 'dismissed' || f.status === 'corrected'
    || (o.recommendation === 'confirm' && f.status !== 'confirmed' && f.status !== 'correction_accepted'))

  return (
    <div className={`card rise relative overflow-hidden p-5 pl-6 ${dismissed ? 'opacity-60' : ''} ${isEvidenceGap ? '!border-amber-300' : ''}`}>
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ background: isEvidenceGap ? '#ffc107' : SEVERITY_COLOR[f.severity] }} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
         <IconBubble color={CATEGORY_COLOR[f.category]} size={42}><Layers size={20} /></IconBubble>
         <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[16px] font-semibold">{checkLabel(f.check_id)}</span>
            <SeverityBadge severity={f.severity} />
            <StatusTag status={f.status} />
            {f.status === 'escalated' && f.escalated_to && (
              <Tag color="red" className="!m-0">to {ESCALATE_LABEL[f.escalated_to] ?? titleCase(f.escalated_to)}</Tag>
            )}
          </div>
          <div className="mono mt-0.5 text-[12px] text-slate-400">
            {f.finding_id}{f.decided_by ? ` · decided by ${f.decided_by}${f.decided_at ? `, ${fmtDateTime(f.decided_at)}` : ''}` : ''}
          </div>
         </div>
        </div>
        <div className="text-right">
          {hasAmount ? (
            <>
              <div className="num text-[22px] font-semibold leading-tight">{money(shownAmount, f.currency)}</div>
              {f.status === 'corrected' && f.corrected_amount != null && (
                <div className="num text-[12px] text-slate-400 line-through">{money(f.amount, f.currency)}</div>
              )}
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

      {c && (
        <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50/60 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-[#2F7FF2]">Recommended correction</span>
            <span className="mono rounded bg-white px-1.5 py-0.5 text-[11.5px] ring-1 ring-blue-200">
              {c.rule_id}{c.clause_id ? ` · clause ${c.clause_id}` : ''}
            </span>
          </div>
          <div className="mt-1 text-[14px] font-medium">{c.label}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[14px]">
            <span className="num text-slate-500 line-through">{money(c.original_amount, f.currency)}</span>
            <ArrowRight size={14} className="text-slate-400" />
            <span className="num font-semibold">{money(c.corrected_amount, f.currency)}</span>
            <Tag color="blue" className="!m-0">− {money(c.delta, f.currency)}</Tag>
            <span className="muted text-[12px]">basis: {titleCase(c.basis)}</span>
          </div>
          {c.calculation && <div className="mono mt-1.5 whitespace-pre-wrap text-[12.5px] text-slate-700">{c.calculation}</div>}
          {c.rule_text && <div className="mt-1 text-[12.5px] text-slate-600">{c.rule_text}</div>}
        </div>
      )}

      {f.recommendation && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-[13px]">
          <Bot size={16} className="mt-0.5 shrink-0 text-[#2F7FF2]" />
          <div>
            <span className="font-medium">AI investigator recommends: </span>{RECOMMEND_LABEL[f.recommendation] ?? titleCase(f.recommendation)}
            {f.recommendation_confidence != null && <span className="muted"> · {Math.round(f.recommendation_confidence * 100)}% confident</span>}
            {f.recommendation_note && <div className="mt-0.5 text-slate-600">{f.recommendation_note}</div>}
          </div>
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
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Supporting records</div>
          <ul className="mt-1.5 space-y-1">
            {f.evidence.map((e, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-2 text-[13px]">
                <Tag color={SOURCE_COLOR[e.source] ?? 'default'} className="!m-0">{e.source.replace('_', ' ')}</Tag>
                <span className="mono text-[12px] text-slate-500">{e.ref}</span>
                {e.quote && <span className="text-slate-800">“{e.quote}”</span>}
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

      {decided && f.reviewer_note && (
        <div className="mt-3 rounded-lg bg-slate-50 p-2.5 text-[13px]"><span className="font-medium">Reviewer note: </span>{f.reviewer_note}</div>
      )}
      {decided && f.decision_reason && (
        <div className="mt-2 rounded-lg bg-slate-50 p-2.5 text-[13px]"><span className="font-medium">Reason: </span>{f.decision_reason}</div>
      )}
      {o && overridden && (
        <div className="mt-2 rounded-lg border border-dashed border-slate-300 p-2.5 text-[12.5px] text-slate-600">
          <span className="font-medium">Original recommendation: </span>
          {money(o.amount, f.currency)} {o.amount_kind}
          {o.correction ? ` · ${o.correction.label}: ${money(o.correction.original_amount, f.currency)} → ${money(o.correction.corrected_amount, f.currency)}` : ''}
          {o.recommendation ? ` · AI: ${RECOMMEND_LABEL[o.recommendation] ?? o.recommendation}` : ''}
          {o.captured_at ? <span className="muted"> · captured {fmtDateTime(o.captured_at)}</span> : null}
        </div>
      )}
      {history.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Decision history</div>
          <ul className="m-0 mt-1 list-none space-y-0.5 p-0 text-[12.5px]">
            {[...history].reverse().map((h, i) => (
              <li key={i} className="text-slate-700">
                <span className="muted">{fmtDateTime(h.ts)}</span> · <b>{h.by || 'unknown'}</b> · {titleCase(h.action ?? '')}
                {h.to_status ? <span className="muted"> → {titleCase(h.to_status)}</span> : null}
                {h.amount != null ? ` · ${money(h.amount, f.currency)}` : ''}
                {h.escalate_to ? ` · to ${ESCALATE_LABEL[h.escalate_to] ?? h.escalate_to}` : ''}
                {h.reason ? <span className="text-slate-500"> · “{h.reason}”</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 border-t border-slate-100 pt-3">
        <Input.TextArea rows={1} autoSize={{ minRows: 1, maxRows: 3 }} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={decided ? 'Add a note and change the decision…' : 'Reviewer note (kept in the audit log)'} className="mb-2" />
        <Space wrap>
          {c && (
            <Button type="primary" icon={<CheckCheck size={14} />} loading={busy} disabled={f.status === 'correction_accepted'}
              onClick={() => onReview({ action: 'accept_correction', note })}>Accept correction</Button>
          )}
          <Button type={c ? 'default' : 'primary'} icon={<Check size={14} />} loading={busy} disabled={f.status === 'confirmed'}
            onClick={() => onReview({ action: 'confirm', note })}>Confirm discrepancy</Button>
          <Button danger icon={<X size={14} />} loading={busy} disabled={dismissed}
            onClick={() => { setFpReason(''); setFpOpen(true) }}>False positive</Button>
          <Button icon={<MessageCircleQuestion size={14} />} loading={busy} disabled={f.status === 'clarification_requested'}
            onClick={() => onReview({ action: 'request_evidence', note })}>Request evidence</Button>
          <Button icon={<ShieldAlert size={14} />} loading={busy} disabled={f.status === 'escalated'}
            onClick={() => { setEscNote(note); setEscOpen(true) }}>Escalate</Button>
          <Popover open={correctOpen} onOpenChange={setCorrectOpen} trigger="click" title="Correct the amount"
            content={(
              <div className="flex w-64 flex-col gap-2">
                <InputNumber min={0} className="!w-full" value={amount} onChange={setAmount} prefix={f.currency}
                  placeholder="Corrected amount" autoFocus />
                <Input.TextArea rows={2} value={correctReason} onChange={(e) => setCorrectReason(e.target.value)} placeholder="Reason (required)" />
                <Button type="primary" size="small" disabled={amount === null || !correctReason.trim()} loading={busy}
                  onClick={() => { onReview({ action: 'correct', amount: amount ?? 0, reason: correctReason.trim(), note }); setCorrectOpen(false) }}>
                  Save correction
                </Button>
              </div>
            )}>
            <Button icon={<Pencil size={14} />} disabled={isEvidenceGap}>Correct amount</Button>
          </Popover>
        </Space>
      </div>

      <Modal open={fpOpen} title="Mark as a false positive" okText="Mark false positive"
        okButtonProps={{ danger: true, disabled: !fpReason.trim() }} onCancel={() => setFpOpen(false)}
        onOk={() => { onReview({ action: 'false_positive', reason: fpReason.trim(), note }); setFpOpen(false) }}>
        <div className="muted mb-2 text-[13px]">Say why this finding is not leakage. The reason is kept in the audit log and the report.</div>
        <Input.TextArea rows={3} value={fpReason} onChange={(e) => setFpReason(e.target.value)} placeholder="Reason (required)" autoFocus />
      </Modal>
      <Modal open={escOpen} title="Escalate this finding" okText="Escalate" onCancel={() => setEscOpen(false)}
        onOk={() => { const n = escNote.trim(); onReview({ action: 'escalate', escalate_to: escTo, note: n || undefined, reason: n || undefined }); setEscOpen(false) }}>
        <Radio.Group value={escTo} onChange={(e) => setEscTo(e.target.value)} className="!mb-3 !flex flex-col gap-1.5">
          <Radio value="senior_reviewer">Senior claims reviewer</Radio>
          <Radio value="siu">Special Investigation Unit</Radio>
        </Radio.Group>
        <Input.TextArea rows={3} value={escNote} onChange={(e) => setEscNote(e.target.value)} placeholder="Note for the reviewer" />
      </Modal>
    </div>
  )
}
