import { Link, useParams } from 'react-router-dom'
import { Alert, Skeleton, Steps, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText } from 'lucide-react'
import { api } from '../api/client'
import { money, titleCase } from '../lib/format'
import { PortalShell } from './PortalSubmitPage'

const DONE = new Set(['settled', 'failed'])

const stepStatus = (s: string): 'wait' | 'process' | 'finish' | 'error' =>
  s === 'done' || s === 'completed' || s === 'finished' ? 'finish' : s === 'running' || s === 'active' || s === 'in_progress' ? 'process'
    : s === 'failed' || s === 'error' ? 'error' : 'wait'

export default function PortalStatusPage() {
  const { claimId = '' } = useParams()
  const q = useQuery({
    queryKey: ['portal', claimId], queryFn: () => api.portalStatus(claimId),
    refetchInterval: (query) => (query.state.data && DONE.has(query.state.data.status) ? false : 2000),
  })
  const p = q.data

  return (
    <PortalShell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="muted text-[13px]">Your claim</div>
          <h1 className="mono m-0 text-[26px] font-semibold tracking-tight">{claimId}</h1>
        </div>
        {p && <Tag color={p.status === 'failed' ? 'red' : p.status === 'settled' ? 'green' : 'processing'} className="!m-0 !px-3 !py-1 !text-[13px]">{titleCase(p.status)}</Tag>}
      </div>
      {q.isError && <Alert className="!mt-4" type="warning" showIcon message="Status is not available yet" description={(q.error as Error).message} />}
      {!p && !q.isError && <Skeleton active className="!mt-4" />}
      {p && (
        <div className="mt-5 flex flex-col gap-4">
          <div className="card p-6">
            <Steps direction="vertical" size="small" items={p.steps.map((s) => ({
              title: s.label, status: stepStatus(s.status),
              description: s.seconds != null ? `${s.seconds.toFixed(1)} s` : undefined,
            }))} />
            {p.message && <div className="mt-2 text-[14px]">{p.message}</div>}
          </div>
          <div className="card p-6">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
              {p.amount_claimed != null && <span><span className="muted">Amount claimed </span><b>{money(p.amount_claimed, p.currency)}</b></span>}
              {p.pages_read != null && <span><span className="muted">Pages read </span><b>{p.pages_read}</b></span>}
              {p.lines_read != null && <span><span className="muted">Bill lines read </span><b>{p.lines_read}</b></span>}
              {p.read_seconds != null && <span><span className="muted">Reading took </span><b>{p.read_seconds.toFixed(1)} s</b></span>}
            </div>
            <ul className="m-0 mt-3 list-none space-y-1.5 p-0">
              {p.documents.map((d, i) => (
                <li key={`${d.name}-${i}`} className="flex items-center gap-2 text-[13px]">
                  <FileText size={15} className="text-slate-400" /> <span className="font-medium">{d.name}</span>
                  <span className="muted">· {d.pages} page{d.pages === 1 ? '' : 's'}</span>
                  {d.type && <Tag className="!m-0">{titleCase(d.type)}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <div className="mt-5 flex gap-4 text-[13px]">
        <Link to="/submit">Submit another claim</Link>
        <Link to={`/claims/${encodeURIComponent(claimId)}`} className="inline-flex items-center gap-1">Open in analyst workspace <ExternalLink size={13} /></Link>
      </div>
    </PortalShell>
  )
}
