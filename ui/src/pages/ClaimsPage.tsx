import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Progress, Table, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Inbox, Play } from 'lucide-react'
import { api } from '../api/client'
import type { ClaimSummary } from '../api/types'
import { SeverityBadge } from '../components/Badges'
import ErrorBox from '../components/ErrorBox'
import FilterBar from '../components/FilterBar'
import { Avatar, Empty } from '../components/ui'
import { fmtDate, money, titleCase } from '../lib/format'
import { useFilters } from '../lib/filters'
import { runMany } from '../lib/runs'

const SEV_RANK = { high: 3, medium: 2, low: 1 } as const
type View = 'all' | 'flagged' | 'open' | 'clean' | 'unchecked'

const isUnchecked = (c: ClaimSummary) => ['ingested', 'classified', 'extracted'].includes(c.status)

export default function ClaimsPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { filters } = useFilters()
  const [view, setView] = useState<View>('all')
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const claims = useQuery({ queryKey: ['claims', filters], queryFn: () => api.listClaims(filters) })
  const all = claims.data ?? []

  const counts: Record<View, number> = useMemo(() => ({
    all: all.length,
    flagged: all.filter((c) => c.findings > 0).length,
    open: all.filter((c) => c.open_findings > 0).length,
    clean: all.filter((c) => !isUnchecked(c) && c.findings === 0).length,
    unchecked: all.filter(isUnchecked).length,
  }), [all])

  const rows = all.filter((c) => (
    view === 'flagged' ? c.findings > 0 : view === 'open' ? c.open_findings > 0 : view === 'clean' ? !isUnchecked(c) && c.findings === 0
      : view === 'unchecked' ? isUnchecked(c) : true))

  const runAll = async () => {
    const ids = all.filter(isUnchecked).map((c) => c.claim_id)
    setProgress({ done: 0, total: ids.length })
    const { failed } = await runMany(ids, (done, total) => setProgress({ done, total }))
    setProgress(null)
    qc.invalidateQueries()
    if (failed.length) message.warning(`${failed.length} claim(s) failed: ${failed.slice(0, 3).join(', ')}`)
    else message.success(`Checked ${ids.length} claim(s)`)
  }

  const columns: ColumnsType<ClaimSummary> = [
    { title: 'Claim', dataIndex: 'claim_id', width: 190,
      render: (v: string, r) => (
        <div className="flex items-center gap-3">
          <Avatar text={r.claimant} size={36} />
          <div className="leading-tight"><div className="mono text-[13px] font-semibold">{v}</div>
            <div className="muted text-[11.5px]">{titleCase(r.claim_type)} · {fmtDate(r.incident_date)}</div></div>
        </div>) },
    { title: 'Provider', dataIndex: 'provider', ellipsis: true },
    { title: 'Requested', dataIndex: 'requested_amount', align: 'right', className: 'num', width: 130,
      render: (v: number, r) => money(v, r.currency), sorter: (a, b) => a.requested_amount - b.requested_amount },
    { title: 'Calculated', dataIndex: 'leakage_calculated', align: 'right', width: 130,
      render: (v: number, r) => (v > 0 ? <span className="num inline-block rounded-full bg-red-50 px-2.5 py-0.5 text-[13px] font-semibold text-red-600">{money(v, r.currency)}</span> : <span className="muted">—</span>),
      sorter: (a, b) => a.leakage_calculated - b.leakage_calculated },
    { title: 'Suspected', dataIndex: 'leakage_suspected', align: 'right', width: 130,
      render: (v: number, r) => (v > 0 ? <span className="num inline-block rounded-full bg-amber-50 px-2.5 py-0.5 text-[13px] font-semibold text-amber-600">{money(v, r.currency)}</span> : <span className="muted">—</span>),
      sorter: (a, b) => a.leakage_suspected - b.leakage_suspected },
    { title: 'Severity', dataIndex: 'severity', width: 110, render: (v) => <SeverityBadge severity={v} />,
      sorter: (a, b) => (a.severity ? SEV_RANK[a.severity] : 0) - (b.severity ? SEV_RANK[b.severity] : 0) },
    { title: 'Findings', dataIndex: 'findings', width: 130, align: 'center',
      render: (v: number, r) => (v === 0 ? <span className="muted">0</span> : <span>{v}{r.open_findings > 0 && <Tag color="green" className="!ml-1.5">{r.open_findings} open</Tag>}</span>) },
    { title: 'Status', dataIndex: 'status', width: 110, render: (v: string) => <Tag className="!m-0 !rounded-full">{titleCase(v)}</Tag> },
  ]

  const chips: { key: View; label: string }[] = [
    { key: 'all', label: 'All' }, { key: 'flagged', label: 'Flagged' }, { key: 'open', label: 'Needs review' },
    { key: 'clean', label: 'Clean' }, { key: 'unchecked', label: 'Not yet checked' },
  ]

  return (
    <div className="flex flex-col gap-5">
      <section className="hero rise p-7">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="eyebrow">Claims queue</div>
            <h1 className="mb-1 mt-1.5 text-[26px] font-semibold tracking-tight text-white">Review flagged claims</h1>
            <p className="m-0 max-w-xl text-[13.5px] text-white/65">Open a claim to see the rule, the calculation and the evidence behind every finding.</p>
          </div>
          <div className="flex items-center gap-3">
            {progress && <Progress type="circle" size={40} percent={Math.round((progress.done / progress.total) * 100)} strokeColor="#55ffbe" trailColor="rgba(255,255,255,.15)" format={(p) => <span className="text-[11px] text-white">{p}%</span>} />}
            <Button type="primary" size="large" icon={<Play size={15} />} disabled={!counts.unchecked || !!progress} loading={!!progress} onClick={runAll}>
              Run checks on {counts.unchecked} unchecked
            </Button>
          </div>
        </div>
      </section>

      <FilterBar />

      <div className="flex flex-wrap gap-2">
        {chips.map((c) => (
          <button key={c.key} type="button" onClick={() => setView(c.key)}
            className={`cursor-pointer rounded-full border px-4 py-1.5 text-[13px] font-medium transition ${
              view === c.key ? 'border-brand bg-brand text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-accent hover:text-brand'}`}>
            {c.label} <span className={`ml-1 ${view === c.key ? 'text-accent' : 'text-slate-400'}`}>{counts[c.key]}</span>
          </button>
        ))}
      </div>

      {claims.isError ? <ErrorBox error={claims.error} onRetry={() => claims.refetch()} /> : (
        <div className="card overflow-hidden rise">
          <Table<ClaimSummary> rowKey="claim_id" size="middle" loading={claims.isLoading} columns={columns} dataSource={rows}
            pagination={{ pageSize: 12, showSizeChanger: false, showTotal: (t) => `${t} claims`, className: '!px-4' }} scroll={{ x: 1100 }}
            rowClassName="clickable" onRow={(r) => ({ onClick: () => nav(`/claims/${encodeURIComponent(r.claim_id)}`) })}
            locale={{ emptyText: <Empty icon={<Inbox size={26} />} title="No claims here" text="Nothing matches these filters. Adjust them, or upload data on the Ingest page." /> }} />
        </div>
      )}
    </div>
  )
}
