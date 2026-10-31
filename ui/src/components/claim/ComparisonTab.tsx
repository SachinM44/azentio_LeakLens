import { useState } from 'react'
import { Alert, Empty, Segmented, Skeleton, Spin, Table, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { ComparisonField, ComparisonLine, DocSource } from '../../api/types'
import { fmtDateTime, money, titleCase } from '../../lib/format'
import EvidenceViewer from './EvidenceViewer'

const FIELD_COLOR: Record<string, string> = { match: 'green', mismatch: 'red', only_in_claim: 'gold', only_in_document: 'blue', not_read: 'default' }
const LINE_COLOR: Record<string, string> = { match: 'green', amount_differs: 'red', only_in_document: 'blue', only_in_claim: 'gold' }

interface Props {
  claimId: string
  currency: string
  onOpenDocument: (documentId: string) => void
}

export default function ComparisonTab({ claimId, currency, onOpenDocument }: Props) {
  const [lineFilter, setLineFilter] = useState<string>('all')
  const [evidence, setEvidence] = useState<DocSource | null>(null)
  const q = useQuery({
    queryKey: ['comparison', claimId], queryFn: () => api.comparison(claimId),
    refetchInterval: (query) => (query.state.data && !query.state.data.extracted ? 3000 : false),
  })

  if (q.isLoading) return <Skeleton active paragraph={{ rows: 6 }} />
  if (q.isError) return <Alert type="info" showIcon message="Document comparison is not available yet" description={(q.error as Error).message} />
  const c = q.data
  if (!c) return <Empty description="No comparison yet." />
  if (!c.extracted) {
    return <div className="card flex items-center justify-center gap-3 p-10 text-[14px]"><Spin /> Documents are being read…</div>
  }

  const source = (s: DocSource | null) => (s ? (
    <button type="button" onClick={() => setEvidence(s)}
      className="cursor-pointer border-0 bg-transparent p-0 text-left text-[12.5px] text-[#2F7FF2] hover:underline">
      {s.document_name}{s.page ? ` · page ${s.page}` : ''}
    </button>
  ) : <span className="muted">—</span>)

  const counts: Record<string, number> = { all: c.lines.length }
  c.lines.forEach((l) => { counts[l.status] = (counts[l.status] ?? 0) + 1 })
  const lines = lineFilter === 'all' ? c.lines : c.lines.filter((l) => l.status === lineFilter)
  const s = c.summary

  return (
    <div className="flex flex-col gap-4">
      <div className="card flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-[13px]">
        <span>Extracted by <Tag color={c.extracted_by === 'ai-vision' ? 'purple' : 'blue'} className="!m-0">{c.extracted_by === 'ai-vision' ? 'AI vision' : 'AI text'}</Tag></span>
        {c.model && <span><span className="muted">Model </span><span className="mono text-[12px]">{c.model}</span></span>}
        {c.read_seconds != null && <span><span className="muted">Read in </span><b>{c.read_seconds.toFixed(1)} s</b></span>}
        {c.extracted_at && <span className="muted">{fmtDateTime(c.extracted_at)}</span>}
        <span className="muted">{c.documents.length} document{c.documents.length === 1 ? '' : 's'}</span>
      </div>

      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="card p-4"><div className="muted text-[12px]">Fields mismatched</div><div className="num text-[20px] font-semibold">{s.fields_mismatched} / {s.fields_checked}</div></div>
          <div className="card p-4"><div className="muted text-[12px]">Claim total</div><div className="num text-[20px] font-semibold">{money(s.claim_total, currency)}</div></div>
          <div className="card p-4"><div className="muted text-[12px]">Document total</div><div className="num text-[20px] font-semibold">{money(s.document_total, currency)}</div></div>
          <div className="card p-4"><div className="muted text-[12px]">Difference</div>
            <div className={`num text-[20px] font-semibold ${Math.abs(s.total_difference) >= 1 ? 'text-red-600' : ''}`}>{money(s.total_difference, currency)}</div></div>
        </div>
      )}

      <section className="card p-5">
        <h2 className="m-0 mb-3 text-[15px] font-semibold">Claim fields vs documents</h2>
        <Table<ComparisonField> size="small" rowKey="field" dataSource={c.fields} pagination={false}
          locale={{ emptyText: 'No fields were compared.' }}
          columns={[
            { title: 'Field', dataIndex: 'label', width: 170, render: (v: string) => <span className="font-medium">{v}</span> },
            { title: 'Claim value', dataIndex: 'claim_value', render: (v) => (v == null || v === '' ? <span className="muted">—</span> : String(v)) },
            { title: 'Document value', dataIndex: 'document_value', render: (v) => (v == null || v === '' ? <span className="muted">—</span> : String(v)) },
            { title: 'Status', dataIndex: 'status', width: 150, render: (v: string) => <Tag color={FIELD_COLOR[v] ?? 'default'} className="!m-0">{titleCase(v)}</Tag> },
            { title: 'Source', dataIndex: 'source', width: 190, render: (v: DocSource | null) => source(v) },
          ]} />
      </section>

      <section className="card p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 text-[15px] font-semibold">Bill lines vs claim lines</h2>
          <Segmented size="small" value={lineFilter} onChange={(v) => setLineFilter(String(v))}
            options={['all', 'match', 'amount_differs', 'only_in_document', 'only_in_claim'].map((k) => ({ value: k, label: `${titleCase(k)} ${counts[k] ?? 0}` }))} />
        </div>
        <Table<ComparisonLine> size="small" rowKey={(r) => `${r.status}|${r.claim_line_id ?? ""}|${r.code ?? ""}|${r.description}|${r.document_amount ?? ""}|${r.claim_amount ?? ""}`} dataSource={lines}
          pagination={{ pageSize: 15, hideOnSinglePage: true }} locale={{ emptyText: 'No lines in this view.' }}
          columns={[
            { title: 'Status', dataIndex: 'status', width: 150, render: (v: string) => <Tag color={LINE_COLOR[v] ?? 'default'} className="!m-0">{titleCase(v)}</Tag> },
            { title: 'Code', dataIndex: 'code', width: 100, render: (v?: string | null) => (v ? <span className="mono text-[12px]">{v}</span> : '—') },
            { title: 'Description', dataIndex: 'description' },
            { title: 'Claim', dataIndex: 'claim_amount', align: 'right', className: 'num', render: (v?: number | null) => money(v, currency) },
            { title: 'Document', dataIndex: 'document_amount', align: 'right', className: 'num', render: (v?: number | null) => money(v, currency) },
            { title: 'Difference', dataIndex: 'difference', align: 'right', className: 'num',
              render: (v?: number | null) => (v ? <b className="text-red-600">{money(v, currency)}</b> : '—') },
            { title: 'Source', dataIndex: 'source', width: 170, render: (v: DocSource | null) => source(v) },
          ]} />
      </section>
      <EvidenceViewer source={evidence} comparison={c} currency={currency} onClose={() => setEvidence(null)}
        onOpenDocuments={onOpenDocument} />
    </div>
  )
}
