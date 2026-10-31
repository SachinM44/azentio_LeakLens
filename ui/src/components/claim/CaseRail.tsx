import { useState } from 'react'
import { Button, Input, Tag, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlus, StickyNote } from 'lucide-react'
import { api } from '../../api/client'
import type { CaseNote, ClaimDetail } from '../../api/types'
import { fmtDateTime, money } from '../../lib/format'

interface Props {
  detail: ClaimDetail
  notes: CaseNote[]
  notesLocal: boolean
  onOpenEvidence: (source: string, ref: string, quote?: string) => void
}

const SOURCE_COLOR: Record<string, string> = { claim: 'blue', invoice_line: 'geekblue', policy: 'purple', history: 'gold', document: 'cyan', config: 'default' }

/** Side rail of the investigation workspace: leakage summary, key policy terms, analyst notes and an evidence index. */
export default function CaseRail({ detail, notes, notesLocal, onOpenEvidence }: Props) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const { claim, policy, summary } = detail
  const cur = claim.currency

  const add = useMutation({
    mutationFn: () => api.addNote(claim.claim_id, text.trim()),
    onSuccess: () => { setText(''); qc.invalidateQueries({ queryKey: ['notes', claim.claim_id] }); qc.invalidateQueries({ queryKey: ['claim', claim.claim_id] }) },
    onError: (e: Error) => message.error(e.message),
  })

  const evidence = detail.findings.flatMap((f) => f.evidence.map((e) => ({ ...e, finding: f.finding_id })))
  const unique = evidence.filter((e, i) => evidence.findIndex((x) => x.source === e.source && x.ref === e.ref) === i)

  return (
    <aside className="case-rail flex flex-col gap-4 lg:sticky lg:top-0 lg:max-h-[calc(100vh-9.5rem)] lg:self-start lg:overflow-y-auto lg:pb-2 lg:pr-1">
      <section className="card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Leakage on this claim</div>
        <div className="mt-2 grid grid-cols-2 gap-3">
          <div><div className="muted text-[11.5px]">Calculated</div><div className="num text-[18px] font-semibold">{money(summary.leakage_calculated, cur)}</div></div>
          <div><div className="muted text-[11.5px]">Suspected</div><div className="num text-[18px] font-semibold text-amber-600">{money(summary.leakage_suspected, cur)}</div></div>
        </div>
        {detail.settlement && (
          <div className="mt-3 flex items-baseline justify-between border-t border-slate-100 pt-3 text-[13px]">
            <span className="muted">Insurer pays</span><b className="num text-[15px]">{money(detail.settlement.payable, cur)}</b>
          </div>
        )}
      </section>

      {policy && (
        <section className="card p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Policy terms</div>
          <dl className="m-0 mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-[12.5px]">
            <dt className="muted">Cover</dt><dd className="m-0 text-right">{policy.start_date} → {policy.end_date}</dd>
            <dt className="muted">Annual limit</dt><dd className="m-0 text-right num">{money(policy.annual_limit, policy.currency)}</dd>
            <dt className="muted">Deductible</dt><dd className="m-0 text-right num">{money(policy.deductible.amount, policy.currency)}</dd>
            <dt className="muted">Co-pay (IP / OP)</dt><dd className="m-0 text-right">{policy.copay.inpatient_pct}% / {policy.copay.outpatient_pct}%</dd>
            {policy.room_rent_limit_per_day != null && (<><dt className="muted">Room / day</dt><dd className="m-0 text-right num">{money(policy.room_rent_limit_per_day, policy.currency)}</dd></>)}
          </dl>
          {policy.sublimits.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{policy.sublimits.map((s) => <Tag key={s.sublimit_id} className="!m-0">{s.name} {s.basis.startsWith('sessions') ? `${s.limit} sessions/yr` : money(s.limit, policy.currency)}</Tag>)}</div>}
        </section>
      )}

      <section className="card p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500"><StickyNote size={13} /> Analyst notes</div>
        {notesLocal && <div className="mt-1 text-[11.5px] text-amber-700">Saved on this device only: the server has no notes endpoint yet.</div>}
        <div className="mt-2 flex flex-col gap-2">
          {notes.length === 0 && <div className="muted text-[12.5px]">No notes yet.</div>}
          {notes.map((n) => (
            <div key={n.note_id} className="rounded-lg bg-slate-50 p-2.5 text-[12.5px]">
              <div>{n.text}</div>
              <div className="muted mt-1 text-[11px]">{n.author} · {fmtDateTime(n.ts)}</div>
            </div>
          ))}
        </div>
        <Input.TextArea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note to the case file…" className="!mt-3" />
        <Button size="small" type="primary" icon={<MessageSquarePlus size={13} />} className="!mt-2" disabled={!text.trim()} loading={add.isPending} onClick={() => add.mutate()}>
          Add note
        </Button>
      </section>

      <section className="card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Evidence index · {unique.length}</div>
        <ul className="m-0 mt-2 list-none space-y-1 p-0">
          {unique.length === 0 && <li className="muted text-[12.5px]">No evidence recorded yet.</li>}
          {unique.map((e, i) => (
            <li key={i}>
              <button type="button" onClick={() => onOpenEvidence(e.source, e.ref, e.quote)}
                className="flex w-full cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent p-1.5 text-left hover:bg-slate-50">
                <Tag color={SOURCE_COLOR[e.source] ?? 'default'} className="!m-0">{e.source.replace('_', ' ')}</Tag>
                <span className="mono truncate text-[11.5px] text-slate-600">{e.ref}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  )
}
