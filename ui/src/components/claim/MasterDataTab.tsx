import { Descriptions, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CheckCircle2, XCircle } from 'lucide-react'
import type { ClaimDetail, Finding, InvoiceLine } from '../../api/types'
import { checkLabel, fmtDate, money, titleCase } from '../../lib/format'

interface Props {
  detail: ClaimDetail
  highlightLine?: string | null
}

export default function MasterDataTab({ detail, highlightLine }: Props) {
  const { claim, policy, lines, findings } = detail
  const cur = claim.currency
  const byLine = new Map<string, Finding[]>()
  findings.forEach((f) => f.line_ids.forEach((id) => byLine.set(id, [...(byLine.get(id) ?? []), f])))
  const total = lines.reduce((s, l) => s + l.amount, 0)

  const columns: ColumnsType<InvoiceLine> = [
    { title: '#', dataIndex: 'serial_no', width: 48 },
    { title: 'Invoice', dataIndex: 'invoice_no', width: 110, render: (v: string) => <span className="mono text-[12px]">{v}</span> },
    { title: 'Date', dataIndex: 'service_date', width: 110, render: fmtDate },
    { title: 'Code', dataIndex: 'code', width: 100, render: (v?: string | null) => (v ? <span className="mono text-[12px]">{v}</span> : '—') },
    { title: 'Description', dataIndex: 'description' },
    { title: 'Category', dataIndex: 'category', width: 120, render: (v?: string | null) => (v ? titleCase(v) : '—') },
    { title: 'Qty', dataIndex: 'quantity', align: 'right', width: 60 },
    { title: 'Unit price', dataIndex: 'unit_price', align: 'right', className: 'num', render: (v: number | null | undefined) => (v == null ? '—' : money(v, cur)) },
    { title: 'Amount', dataIndex: 'amount', align: 'right', className: 'num', render: (v: number) => <b>{money(v, cur)}</b> },
    { title: 'Page', dataIndex: 'page', width: 60, render: (v?: number | null) => v ?? '—' },
    { title: 'Flags', key: 'flags', width: 190,
      render: (_: unknown, l) => (byLine.get(l.line_id) ?? []).map((f) => (
        <Tag key={f.finding_id} color={f.amount_kind === 'calculated' ? 'red' : 'orange'} className="!mb-0.5">{checkLabel(f.check_id)}</Tag>)) },
  ]

  return (
    <div className="flex flex-col gap-4">
      <section className="card rise p-5">
        <Descriptions size="small" column={{ xs: 1, md: 2, xl: 3 }} title="Claim">
          <Descriptions.Item label="Policy"><span className="mono">{claim.policy_number}</span></Descriptions.Item>
          <Descriptions.Item label="Product">{claim.product_id}</Descriptions.Item>
          <Descriptions.Item label="Claimant ID"><span className="mono">{claim.claimant_id}</span></Descriptions.Item>
          <Descriptions.Item label="Provider">{claim.provider_name || claim.provider_id}</Descriptions.Item>
          <Descriptions.Item label="Incident">{fmtDate(claim.incident_date)}</Descriptions.Item>
          <Descriptions.Item label="Stay">{claim.admission_date ? `${fmtDate(claim.admission_date)} → ${fmtDate(claim.discharge_date)}` : '—'}</Descriptions.Item>
          <Descriptions.Item label="Diagnosis">{claim.diagnosis || '—'}{claim.diagnosis_code ? ` (${claim.diagnosis_code})` : ''}</Descriptions.Item>
          <Descriptions.Item label="Invoices">{claim.invoice_numbers.join(', ') || '—'}</Descriptions.Item>
          <Descriptions.Item label="Source">{titleCase(claim.source ?? 'structured')}</Descriptions.Item>
        </Descriptions>
      </section>

      <section className="card rise p-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="m-0 text-[15px] font-semibold">Invoice lines</h3>
          {detail.reconciled != null && (
            <span className={`inline-flex items-center gap-1.5 text-[13px] font-medium ${detail.reconciled ? 'text-green-600' : 'text-red-600'}`}>
              {detail.reconciled ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
              lines {detail.reconciled ? '=' : '≠'} printed total
              {detail.printed_total != null && <span className="num font-normal text-slate-500"> ({money(total, cur)} vs {money(detail.printed_total, cur)})</span>}
            </span>
          )}
        </div>
        <Table<InvoiceLine> size="small" rowKey="line_id" columns={columns} dataSource={lines} pagination={false} scroll={{ x: 1000 }}
          rowClassName={(l) => (l.line_id === highlightLine ? 'bg-yellow-50' : byLine.has(l.line_id) ? 'bg-red-50/40' : '')}
          summary={() => (lines.length ? (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={8}><b>Total ({lines.length} lines)</b></Table.Summary.Cell>
              <Table.Summary.Cell index={8} align="right"><b className="num">{money(total, cur)}</b></Table.Summary.Cell>
              <Table.Summary.Cell index={9} colSpan={2} />
            </Table.Summary.Row>) : null)}
          locale={{ emptyText: 'No invoice lines on this claim.' }} />
      </section>

      {policy && (
        <section className="card rise p-5">
          <Descriptions size="small" column={{ xs: 1, md: 2, xl: 3 }} title={`Policy ${policy.policy_number}`}>
            <Descriptions.Item label="Cover period">{fmtDate(policy.start_date)} → {fmtDate(policy.end_date)}</Descriptions.Item>
            <Descriptions.Item label="Annual limit">{money(policy.annual_limit, policy.currency)}</Descriptions.Item>
            <Descriptions.Item label="Deductible">{money(policy.deductible.amount, policy.currency)} ({policy.deductible.basis.replace('_', ' ')})</Descriptions.Item>
            <Descriptions.Item label="Co-pay">IP {policy.copay.inpatient_pct}% · OP {policy.copay.outpatient_pct}% · Pharmacy {policy.copay.pharmacy_pct}%</Descriptions.Item>
            <Descriptions.Item label="Room rent / day">{policy.room_rent_limit_per_day != null ? money(policy.room_rent_limit_per_day, policy.currency) : '—'}</Descriptions.Item>
            <Descriptions.Item label="ICU / day">{policy.icu_limit_per_day != null ? money(policy.icu_limit_per_day, policy.currency) : '—'}</Descriptions.Item>
            <Descriptions.Item label="Waiting period">{policy.waiting_period_days} days</Descriptions.Item>
            <Descriptions.Item label="Network">{policy.network_provider_ids.length ? `${policy.network_provider_ids.length} providers` : 'Any provider'}</Descriptions.Item>
          </Descriptions>
          <div className="mt-3 grid gap-3 md:grid-cols-3 text-[13px]">
            <div><div className="mb-1 font-semibold">Sub-limits</div>
              {policy.sublimits.length ? policy.sublimits.map((s) => (
                <div key={s.sublimit_id}>{s.name}: {money(s.limit, policy.currency)} <span className="muted">({s.basis.replace(/_/g, ' ')}{s.clause_id ? `, cl. ${s.clause_id}` : ''})</span></div>
              )) : <span className="muted">None</span>}</div>
            <div><div className="mb-1 font-semibold">Exclusions</div>
              {policy.exclusions.length ? policy.exclusions.map((e) => (
                <div key={e.exclusion_id}><b>{e.exclusion_id}</b> {e.clause_id && <span className="muted">cl. {e.clause_id} </span>}— {e.text}</div>
              )) : <span className="muted">None</span>}</div>
            <div><div className="mb-1 font-semibold">Non-payable items</div>
              {policy.non_payable_items.length ? policy.non_payable_items.map((i) => <Tag key={i}>{i}</Tag>) : <span className="muted">None</span>}</div>
          </div>
        </section>
      )}
    </div>
  )
}
