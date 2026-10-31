import { Link } from 'react-router-dom'
import { Button, Descriptions, Drawer, Skeleton, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, FileText } from 'lucide-react'
import { api } from '../api/client'
import type { ClaimDetail } from '../api/types'
import { fmtDate, money, titleCase } from '../lib/format'

export interface EvidenceRef { source: string; ref: string; quote?: string }

interface Props {
  evidence: EvidenceRef | null
  detail: ClaimDetail
  onClose: () => void
  onOpenTab: (tab: string, line?: string) => void
}

/** Inspect one piece of supporting evidence: what it says, and the underlying record it points to. */
export default function EvidenceDrawer({ evidence, detail, onClose, onOpenTab }: Props) {
  const ref = evidence?.ref ?? ''
  const claimRef = ref.split('/')[0]
  const isClaim = !!evidence && (evidence.source === 'claim' || evidence.source === 'history') && /^CLM/i.test(claimRef)
  const other = useQuery({ queryKey: ['claim', claimRef], queryFn: () => api.getClaim(claimRef), enabled: isClaim && claimRef !== detail.claim.claim_id, retry: false })
  const line = evidence?.source === 'invoice_line' ? detail.lines.find((l) => l.line_id === ref) : undefined
  const doc = evidence?.source === 'document' ? detail.documents.find((d) => d.id === ref || d.name === ref) : undefined

  return (
    <Drawer open={!!evidence} onClose={onClose} width={460} title={evidence ? `Evidence: ${titleCase(evidence.source)}` : ''}>
      {evidence && (
        <div className="flex flex-col gap-4">
          <div>
            <div className="muted text-[11px] font-semibold uppercase tracking-wide">Reference</div>
            <div className="mono mt-1 text-[13px]">{evidence.ref}</div>
          </div>
          {evidence.quote && (
            <div className="rounded-xl bg-slate-50 p-3.5">
              <div className="muted text-[11px] font-semibold uppercase tracking-wide">As recorded</div>
              <div className="mt-1 text-[14px]">“{evidence.quote}”</div>
            </div>
          )}

          {line && (
            <Descriptions size="small" column={1} bordered title="Invoice line">
              <Descriptions.Item label="Description">{line.description}</Descriptions.Item>
              <Descriptions.Item label="Invoice / #">{line.invoice_no} / {line.serial_no}</Descriptions.Item>
              <Descriptions.Item label="Date">{fmtDate(line.service_date)}</Descriptions.Item>
              <Descriptions.Item label="Code">{line.code ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Quantity × price">{line.quantity} × {line.unit_price != null ? money(line.unit_price, detail.claim.currency) : '—'}</Descriptions.Item>
              <Descriptions.Item label="Amount"><b>{money(line.amount, detail.claim.currency)}</b></Descriptions.Item>
            </Descriptions>
          )}
          {line && <Button onClick={() => { onOpenTab('master', line.line_id); onClose() }}>Show in master data</Button>}

          {isClaim && claimRef === detail.claim.claim_id && <Tag className="!m-0 w-fit">This claim</Tag>}
          {isClaim && claimRef !== detail.claim.claim_id && (
            other.isLoading ? <Skeleton active paragraph={{ rows: 4 }} /> : other.data ? (
              <>
                <Descriptions size="small" column={1} bordered title={`Claim ${claimRef}`}>
                  <Descriptions.Item label="Provider">{other.data.claim.provider_name || other.data.claim.provider_id}</Descriptions.Item>
                  <Descriptions.Item label="Policy">{other.data.claim.policy_number}</Descriptions.Item>
                  <Descriptions.Item label="Incident">{fmtDate(other.data.claim.incident_date)}</Descriptions.Item>
                  <Descriptions.Item label="Invoices">{other.data.claim.invoice_numbers.join(', ') || '—'}</Descriptions.Item>
                  <Descriptions.Item label="Requested"><b>{money(other.data.claim.requested_amount, other.data.claim.currency)}</b></Descriptions.Item>
                </Descriptions>
                <Link to={`/claims/${encodeURIComponent(claimRef)}`} onClick={onClose}><Button icon={<ArrowUpRight size={14} />}>Open claim {claimRef}</Button></Link>
              </>
            ) : <div className="muted text-[13px]">The underlying claim is not in the current dataset (it may be an earlier paid claim).</div>
          )}

          {evidence.source === 'document' && (
            <div className="flex flex-col gap-2">
              {doc && <div className="text-[13px]"><FileText size={14} className="mr-1 inline" /> {doc.name} · {doc.pages} page(s)</div>}
              <Button icon={<FileText size={14} />} onClick={() => { onOpenTab('documents'); onClose() }}>Open the documents</Button>
              <Button onClick={() => { onOpenTab('comparison'); onClose() }}>See the comparison with the claim</Button>
            </div>
          )}

          {evidence.source === 'policy' && detail.policy && (
            <Descriptions size="small" column={1} bordered title={`Policy ${detail.policy.policy_number}`}>
              <Descriptions.Item label="Cover">{fmtDate(detail.policy.start_date)} to {fmtDate(detail.policy.end_date)}</Descriptions.Item>
              <Descriptions.Item label="Annual limit">{money(detail.policy.annual_limit, detail.policy.currency)}</Descriptions.Item>
              <Descriptions.Item label="Room limit / day">{detail.policy.room_rent_limit_per_day != null ? money(detail.policy.room_rent_limit_per_day, detail.policy.currency) : '—'}</Descriptions.Item>
              <Descriptions.Item label="Deductible">{money(detail.policy.deductible.amount, detail.policy.currency)}</Descriptions.Item>
            </Descriptions>
          )}
          {evidence.source === 'config' && <Link to="/config" onClick={onClose}><Button>Open the rule book</Button></Link>}
        </div>
      )}
    </Drawer>
  )
}
