import { Table, Tag } from 'antd'
import type { AuditRow } from '../../api/types'
import { fmtDateTime, titleCase } from '../../lib/format'

export default function AuditTab({ rows }: { rows: AuditRow[] }) {
  return (
    <Table<AuditRow> size="small" rowKey="audit_id" dataSource={[...rows].reverse()} pagination={{ pageSize: 12, hideOnSinglePage: true }}
      locale={{ emptyText: 'No audit entries for this claim yet.' }} className="card overflow-hidden"
      columns={[
        { title: 'When', dataIndex: 'ts', width: 150, render: fmtDateTime },
        { title: 'Who', dataIndex: 'actor', width: 120 },
        { title: 'Action', dataIndex: 'action', width: 190, render: (v: string) => <Tag className="!m-0">{titleCase(v)}</Tag> },
        { title: 'Details', dataIndex: 'details',
          render: (d: Record<string, unknown>) => (
            <span className="mono text-[12px] text-slate-600">
              {Object.entries(d).filter(([, v]) => v !== null && v !== '' && v !== undefined).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join('  ')}
            </span>) },
      ]} />
  )
}
