import { Empty, Table } from 'antd'
import type { PolicyTerm } from '../../api/types'

export default function PolicyTermsTab({ terms }: { terms: PolicyTerm[] }) {
  if (!terms.length) return <Empty description="No policy terms are available for this claim." />
  return (
    <Table<PolicyTerm> size="small" rowKey={(r) => `${r.term}|${r.value}|${r.clause_id ?? ""}`} dataSource={terms} pagination={false} className="card overflow-hidden"
      columns={[
        { title: 'Term', dataIndex: 'term', render: (v: string) => <span className="font-medium">{v}</span> },
        { title: 'Value', dataIndex: 'value', render: (v: string | number) => <span className="num">{String(v)}</span> },
        { title: 'Clause', dataIndex: 'clause_id', width: 120,
          render: (v?: string | null) => (v ? <span className="mono rounded bg-slate-50 px-1.5 py-0.5 text-[12px] ring-1 ring-slate-200">{v}</span> : '—') },
      ]} />
  )
}
