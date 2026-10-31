import { Alert, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FileDiff } from 'lucide-react'
import type { ClaimDetail } from '../../api/types'
import { buildComparison, type CompareRow, type CompareStatus } from '../../lib/analysis'
import { Empty } from '../ui'

const STATUS: Record<CompareStatus, { color: string; label: string }> = {
  match: { color: 'green', label: 'Matches' },
  mismatch: { color: 'red', label: 'Differs' },
  missing_in_document: { color: 'orange', label: 'Not on document' },
  missing_in_claim: { color: 'orange', label: 'Not in claim' },
}

/** Level 2, document analysis: what the document says against what the claim says, each value with its source. */
export default function DocumentComparisonTab({ detail, onOpenDocuments }: { detail: ClaimDetail; onOpenDocuments: () => void }) {
  const rows = buildComparison(detail)
  if (!rows.length) {
    return <Empty icon={<FileDiff size={26} />} title="Nothing to compare yet"
      text={detail.documents.length
        ? 'Documents are attached but no values have been extracted from them. Confirm the page types on the Classification tab so the bill can be read.'
        : 'No supporting documents are attached to this claim. Upload the invoice or discharge summary on the Ingest page.'} />
  }
  const diffs = rows.filter((r) => r.status !== 'match').length
  const columns: ColumnsType<CompareRow> = [
    { title: 'Field', dataIndex: 'field', width: 220, render: (v: string) => <b className="text-[13px]">{v}</b> },
    { title: 'Claim record', dataIndex: 'claim' },
    { title: 'Document', dataIndex: 'document' },
    { title: 'Result', dataIndex: 'status', width: 140, render: (v: CompareStatus) => <Tag color={STATUS[v].color} className="!m-0">{STATUS[v].label}</Tag> },
    { title: 'Source', dataIndex: 'source', width: 190,
      render: (v?: string) => (v ? <button type="button" onClick={onOpenDocuments} className="mono cursor-pointer border-0 bg-transparent p-0 text-left text-[12px] text-brand hover:underline">{v}</button> : <span className="muted">—</span>) },
  ]
  return (
    <div className="flex flex-col gap-3">
      <Alert showIcon type={diffs ? 'warning' : 'success'}
        message={diffs ? `${diffs} difference${diffs === 1 ? '' : 's'} between the documents and the claim` : 'The documents agree with the claim record'}
        description="Each document value keeps a reference to the file and page it was read from. Click a source to open the document." />
      <Table<CompareRow> size="small" rowKey="key" columns={columns} dataSource={rows} pagination={false} className="card overflow-hidden"
        rowClassName={(r) => (r.status === 'match' ? '' : r.status === 'mismatch' ? 'bg-red-50/50' : 'bg-amber-50/50')}
        expandable={{ rowExpandable: (r) => !!r.note, expandedRowRender: (r) => <span className="text-[13px] text-slate-600">{r.note}</span> }} />
    </div>
  )
}
