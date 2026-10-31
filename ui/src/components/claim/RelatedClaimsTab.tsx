import { Link } from 'react-router-dom'
import { Skeleton, Tag } from 'antd'
import { ArrowUpRight, Link2 } from 'lucide-react'
import type { ClaimDetail } from '../../api/types'
import type { RelatedClaim } from '../../lib/useRelated'
import { checkLabel, fmtDate, money, titleCase } from '../../lib/format'
import { Empty } from '../ui'

const STRENGTH: Record<string, { color: string; label: string }> = {
  strong: { color: 'red', label: 'Strong link' },
  medium: { color: 'orange', label: 'Possible link' },
  weak: { color: 'default', label: 'Context' },
}

function Row({ label, mine, theirs, hit }: { label: string; mine: string; theirs: string; hit: boolean }) {
  return (
    <tr className={hit ? 'bg-amber-50' : ''}>
      <td className="muted w-[28%] py-1.5 pr-3 text-[12.5px]">{label}</td>
      <td className="py-1.5 pr-3 text-[13px]">{mine || '—'}</td>
      <td className="py-1.5 text-[13px]">{theirs || '—'}</td>
    </tr>
  )
}

/** Level 2, cross-claim correlation: related claims side by side, with the matching attributes highlighted. */
export default function RelatedClaimsTab({ detail, related }: { detail: ClaimDetail; related: RelatedClaim[] }) {
  if (!related.length) {
    return <Empty icon={<Link2 size={26} />} title="No related claims found" text="No finding links this claim to another one. Related claims show up here when invoices, members, providers, contacts or incidents overlap." />
  }
  const mine = detail.claim
  return (
    <div className="flex flex-col gap-4">
      <div className="muted text-[13px]">
        {related.length} related claim{related.length === 1 ? '' : 's'}. Highlighted rows are the attributes that connect them to <span className="mono">{mine.claim_id}</span>.
      </div>
      {related.map((r) => {
        const other = r.detail?.claim
        const hit = (label: string) => r.matches.some((m) => m.attribute.toLowerCase().includes(label))
        return (
          <section key={r.claim_id} className="card rise p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <Link2 size={18} className="text-brand" />
                <Link to={`/claims/${encodeURIComponent(r.claim_id)}`} className="mono text-[16px] font-semibold text-brand no-underline hover:underline">{r.claim_id}</Link>
                {other && <span className="muted text-[13px]">{other.provider_name || other.provider_id} · {titleCase(other.claim_type)} · {fmtDate(other.incident_date)}</span>}
              </div>
              <Link to={`/claims/${encodeURIComponent(r.claim_id)}`} className="inline-flex items-center gap-1 text-[13px] text-slate-500 no-underline hover:text-brand">
                Open claim <ArrowUpRight size={14} />
              </Link>
            </div>

            {r.loading && <Skeleton active paragraph={{ rows: 3 }} className="!mt-3" />}
            {r.failed && <div className="mt-3 text-[13px] text-amber-700">This claim could not be loaded, so only the findings below connect it.</div>}

            {r.matches.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {r.matches.map((m, i) => (
                  <Tag key={i} color={STRENGTH[m.strength].color} className="!m-0" title={STRENGTH[m.strength].label}>{m.attribute}</Tag>
                ))}
              </div>
            )}

            {other && (
              <table className="mt-3 w-full border-collapse">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                    <th className="py-1 font-semibold">Attribute</th><th className="py-1 font-semibold">{mine.claim_id}</th><th className="py-1 font-semibold">{other.claim_id}</th>
                  </tr>
                </thead>
                <tbody>
                  <Row label="Invoice numbers" mine={mine.invoice_numbers.join(', ')} theirs={other.invoice_numbers.join(', ')} hit={hit('invoice')} />
                  <Row label="Policy" mine={mine.policy_number} theirs={other.policy_number} hit={hit('polic')} />
                  <Row label="Member" mine={`${mine.claimant_name ?? ''} (${mine.claimant_id})`} theirs={`${other.claimant_name ?? ''} (${other.claimant_id})`} hit={hit('member')} />
                  <Row label="Provider" mine={mine.provider_name || mine.provider_id} theirs={other.provider_name || other.provider_id} hit={hit('provider')} />
                  <Row label="Incident date" mine={fmtDate(mine.incident_date)} theirs={fmtDate(other.incident_date)} hit={hit('dates')} />
                  <Row label="Amount" mine={money(mine.requested_amount, mine.currency)} theirs={money(other.requested_amount, other.currency)} hit={hit('amount')} />
                  {(mine.bank_account || other.bank_account) && <Row label="Bank account" mine={mine.bank_account ?? ''} theirs={other.bank_account ?? ''} hit={hit('bank')} />}
                  {(mine.contact_phone || other.contact_phone) && <Row label="Phone" mine={mine.contact_phone ?? ''} theirs={other.contact_phone ?? ''} hit={hit('phone')} />}
                </tbody>
              </table>
            )}

            {r.because.length > 0 && (
              <div className="mt-3 rounded-xl bg-slate-50 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Why they are connected</div>
                <ul className="m-0 mt-1.5 list-disc space-y-1 pl-5 text-[13px]">
                  {r.because.map((f) => <li key={f.finding_id}><b>{checkLabel(f.check_id)}:</b> {f.reason}</li>)}
                </ul>
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
