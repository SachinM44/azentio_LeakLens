import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Input, InputNumber, Popover, Progress, Space, Tag } from 'antd'
import { Check, Layers, MessageCircleQuestion, Pencil, X } from 'lucide-react'
import type { Finding, ReviewAction } from '../api/types'
import { CATEGORY_COLOR, SEVERITY_COLOR, checkLabel, money } from '../lib/format'
import { IconBubble } from './ui'
import { AmountKindBadge, SeverityBadge, StatusTag } from './Badges'

interface Props {
  finding: Finding
  busy: boolean
  onReview: (action: ReviewAction, note: string, amount?: number) => void
  onLineClick?: (lineId: string) => void
}

const SOURCE_COLOR: Record<string, string> = {
  claim: 'blue', invoice_line: 'geekblue', policy: 'purple', history: 'gold', document: 'cyan', config: 'default',
}

export default function FindingCard({ finding: f, busy, onReview, onLineClick }: Props) {
  const [note, setNote] = useState('')
  const [amount, setAmount] = useState<number | null>(f.corrected_amount ?? (f.amount_kind === 'calculated' ? f.amount : null))
  const [correctOpen, setCorrectOpen] = useState(false)
  const isEvidenceGap = f.category === 'evidence'
  const decided = f.status !== 'open' && f.status !== 'auto_applied'
  const dismissed = f.status === 'dismissed'
  const hasAmount = f.amount > 0

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
          </div>
          <div className="mono mt-0.5 text-[12px] text-slate-400">{f.finding_id}</div>
         </div>
        </div>
        <div className="text-right">
          {hasAmount ? (
            <>
              <div className="num text-[22px] font-semibold leading-tight">
                {money(f.status === 'corrected' && f.corrected_amount != null ? f.corrected_amount : f.amount, f.currency)}
              </div>
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

      <div className="mt-4 border-t border-slate-100 pt-3">
        <Input.TextArea rows={1} autoSize={{ minRows: 1, maxRows: 3 }} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={decided ? 'Add a note and change the decision…' : 'Reviewer note (kept in the audit log)'} className="mb-2" />
        <Space wrap>
          <Button type="primary" icon={<Check size={14} />} loading={busy} disabled={f.status === 'confirmed'}
            onClick={() => onReview('confirm', note)}>Confirm</Button>
          <Popover open={correctOpen} onOpenChange={setCorrectOpen} trigger="click" title="Correct the amount"
            content={(
              <div className="flex w-56 flex-col gap-2">
                <InputNumber min={0} className="!w-full" value={amount} onChange={setAmount} prefix={f.currency}
                  placeholder="Corrected amount" autoFocus />
                <Button type="primary" size="small" disabled={amount === null} loading={busy}
                  onClick={() => { onReview('correct', note, amount ?? 0); setCorrectOpen(false) }}>Save correction</Button>
              </div>
            )}>
            <Button icon={<Pencil size={14} />} disabled={isEvidenceGap}>Correct</Button>
          </Popover>
          <Button danger icon={<X size={14} />} loading={busy} disabled={dismissed} onClick={() => onReview('dismiss', note)}>Dismiss</Button>
          <Button icon={<MessageCircleQuestion size={14} />} loading={busy} disabled={f.status === 'clarification_requested'}
            onClick={() => onReview('clarify', note)}>Request clarification</Button>
        </Space>
      </div>
    </div>
  )
}
