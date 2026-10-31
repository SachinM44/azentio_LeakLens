import { useMemo, useState } from 'react'
import { Button, Segmented, Tag, Timeline } from 'antd'
import { Bot, Download, FileText, Gavel, MessageSquare, Pencil, ScanSearch, Settings2 } from 'lucide-react'
import type { CaseNote, ClaimDetail } from '../../api/types'
import { buildReport, buildTimeline, downloadJson, openPrintableReport, type Match, type TimelineEvent } from '../../lib/analysis'
import { fmtDateTime, money } from '../../lib/format'
import { Empty } from '../ui'

const KIND: Record<TimelineEvent['kind'], { color: string; label: string; icon: JSX.Element }> = {
  detected: { color: '#dc3545', label: 'Detected', icon: <ScanSearch size={14} /> },
  ai: { color: '#7c5cff', label: 'AI recommendation', icon: <Bot size={14} /> },
  decision: { color: '#2ed88e', label: 'Decision', icon: <Gavel size={14} /> },
  override: { color: '#f59e0b', label: 'Override', icon: <Pencil size={14} /> },
  note: { color: '#0dcaf0', label: 'Note', icon: <MessageSquare size={14} /> },
  system: { color: '#9aa6b2', label: 'System', icon: <Settings2 size={14} /> },
}

interface Props {
  detail: ClaimDetail
  notes: CaseNote[]
  related: { claim_id: string; matches: Match[] }[]
  analyst: string
}

/** Level 2, evidence and audit trail: every calculation, issue, AI recommendation, decision, override and note, in order. */
export default function TimelineTab({ detail, notes, related, analyst }: Props) {
  const [filter, setFilter] = useState<'all' | TimelineEvent['kind']>('all')
  const events = useMemo(() => buildTimeline(detail, notes), [detail, notes])
  const shown = events.filter((e) => filter === 'all' || e.kind === filter)
  const report = () => buildReport(detail, notes, related, analyst)

  return (
    <div className="flex flex-col gap-4">
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <div className="text-[15px] font-semibold">Investigation report</div>
          <div className="muted text-[12.5px]">Original calculations, detected issues, AI recommendations, decisions, overrides, notes and timestamps in one file.</div>
        </div>
        <div className="flex gap-2">
          <Button icon={<Download size={14} />} onClick={() => downloadJson(report(), detail.claim.claim_id)}>Download JSON</Button>
          <Button type="primary" icon={<FileText size={14} />} onClick={() => openPrintableReport(report())}>Printable report</Button>
        </div>
      </div>

      <Segmented value={filter} onChange={(v) => setFilter(v as typeof filter)}
        options={[{ value: 'all', label: `All ${events.length}` }, ...(['detected', 'ai', 'decision', 'override', 'note', 'system'] as const)
          .filter((k) => events.some((e) => e.kind === k)).map((k) => ({ value: k, label: KIND[k].label }))]} />

      {!shown.length ? <Empty icon={<ScanSearch size={26} />} title="No history yet" text="Run the checks on this claim to start the evidence history." /> : (
        <div className="card p-5">
          <Timeline items={shown.map((e) => ({
            key: e.key, color: KIND[e.kind].color,
            children: (
              <div className="pb-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13.5px] font-semibold">{e.title}</span>
                  <Tag className="!m-0" color={e.kind === 'override' ? 'orange' : undefined}>{KIND[e.kind].label}</Tag>
                  {e.amount != null && e.amount > 0 && <span className="num text-[12.5px] text-slate-600">{money(e.amount, detail.claim.currency)}</span>}
                </div>
                {e.detail && <div className="mt-0.5 text-[13px] text-slate-700">{e.detail}</div>}
                {e.extra && <div className="mt-0.5 text-[12.5px] text-amber-700">{e.extra}</div>}
                <div className="muted mt-0.5 text-[11.5px]">{fmtDateTime(e.ts)}{e.by ? ` · ${e.by}` : ''}{e.findingId ? ` · ${e.findingId}` : ''}</div>
              </div>
            ),
          }))} />
        </div>
      )}
    </div>
  )
}
