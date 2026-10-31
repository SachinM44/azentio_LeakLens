import { Link } from 'react-router-dom'
import { Alert, Empty, Skeleton, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { RelatedClaim } from '../../api/types'
import { fmtDate, money, titleCase } from '../../lib/format'

const STRENGTH_COLOR: Record<string, string> = { strong: 'red', medium: 'gold', weak: 'default' }

export default function RelatedTab({ claimId }: { claimId: string }) {
  const q = useQuery({ queryKey: ['related', claimId], queryFn: () => api.related(claimId) })
  if (q.isLoading) return <Skeleton active paragraph={{ rows: 4 }} />
  if (q.isError) return <Alert type="info" showIcon message="Related claims are not available yet" description={(q.error as Error).message} />
  const rows: RelatedClaim[] = q.data?.related ?? []
  if (!rows.length) return <Empty description="No other claim shares an invoice, bank account, phone, address or member with this one." />

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((r) => (
        <div key={`${r.source}-${r.claim_id}`} className="card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {r.source === 'claim'
                ? <Link to={`/claims/${encodeURIComponent(r.claim_id)}`} className="mono text-[15px] font-semibold !text-[#2F7FF2] hover:underline">{r.claim_id}</Link>
                : <span className="mono text-[15px] font-semibold">{r.claim_id}</span>}
              {r.source === 'history' && <Tag className="!m-0">Paid history</Tag>}
            </div>
            <div className="flex items-center gap-2">
              <Tag color={STRENGTH_COLOR[r.strength] ?? 'default'} className="!m-0">{titleCase(r.strength)} link</Tag>
              {r.source === 'claim' && (
                <a href={`/claims/${encodeURIComponent(r.claim_id)}`} target="_blank" rel="noreferrer"
                  className="rounded-md border border-[#2F7FF2] px-2 py-0.5 text-[12px] font-medium text-[#2F7FF2] no-underline hover:bg-[#2F7FF2] hover:text-white">
                  Open claim ↗
                </a>
              )}
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
            <div><span className="muted">Member </span>{r.claimant_name || r.claimant_id || '—'}</div>
            <div><span className="muted">Provider </span>{r.provider_name || r.provider_id || '—'}</div>
            <div><span className="muted">Policy </span><span className="mono text-[12px]">{r.policy_number || '—'}</span></div>
            <div><span className="muted">Date </span>{fmtDate(r.incident_date)}</div>
            <div><span className="muted">Amount </span><span className="num">{money(r.requested_amount, r.currency)}</span></div>
            {r.status && <div><span className="muted">Status </span>{titleCase(r.status)}</div>}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {r.matches.map((m, i) => (
              <Tag key={`${m.attribute}-${i}`} color="blue" className="!m-0">{m.label}{m.value ? ` ${m.value}` : ''}</Tag>
            ))}
          </div>
          {r.finding_ids.length > 0 && (
            <div className="muted mt-2 text-[12px]">Findings: <span className="mono">{r.finding_ids.join(', ')}</span></div>
          )}
        </div>
      ))}
    </div>
  )
}
