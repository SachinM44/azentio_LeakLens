import { Alert, Empty } from 'antd'
import type { Settlement } from '../../api/types'
import { checkLabel, money } from '../../lib/format'

function Row({ label, value, sub, strong, minus, cur }: { label: string; value: number; sub?: string; strong?: boolean; minus?: boolean; cur: string }) {
  return (
    <div className={`flex items-baseline justify-between gap-4 py-2 ${strong ? 'border-t-2 border-slate-300 text-[17px] font-semibold' : 'border-t border-slate-100 text-[14px]'}`}>
      <div><span>{label}</span>{sub && <div className="muted text-[12px] font-normal">{sub}</div>}</div>
      <span className="num">{minus && value > 0 ? '− ' : ''}{money(value, cur)}</span>
    </div>
  )
}

export default function SettlementTab({ settlement: s }: { settlement: Settlement | null }) {
  if (!s) return <Empty description="No settlement yet. Run the checks on this claim to calculate one." />
  const cur = s.currency
  const diff = s.difference ?? null
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <section className="card p-5 lg:col-span-3">
        <h3 className="m-0 mb-2 text-[15px] font-semibold">Recalculated settlement</h3>
        <Row label="Amount requested" value={s.requested_amount} cur={cur} />
        <Row label="Invoice lines total" value={s.lines_total} cur={cur}
          sub={s.lines_total !== s.requested_amount ? `differs from the requested amount by ${money(Math.abs(s.requested_amount - s.lines_total), cur)}` : undefined} />
        {s.deductions.map((d) => (
          <Row key={d.finding_id} label={checkLabel(d.check_id)} sub={d.reason} value={d.amount} minus cur={cur} />
        ))}
        <Row label="After leakage deductions" value={s.after_deductions} cur={cur} />
        <Row label="Deductible" value={s.deductible_amount} minus cur={cur} />
        <Row label={`Co-pay (${s.copay_pct}%)`} value={s.copay_amount} minus cur={cur} />
        {s.benefit_cap_applied > 0 && <Row label="Annual benefit limit applied" value={s.benefit_cap_applied} minus cur={cur} />}
        <Row label="Insurer pays" value={s.payable} strong cur={cur} />
        <div className="muted mt-1 text-right text-[12px]">Patient pays {money(s.patient_pays, cur)}</div>
      </section>

      <div className="flex flex-col gap-4 lg:col-span-2">
        <section className="card rise p-5">
          <h3 className="m-0 mb-2 text-[15px] font-semibold">Proposed vs recalculated</h3>
          {s.proposed_settlement == null ? (
            <div className="muted text-[13px]">The handler has not proposed a figure for this claim.</div>
          ) : (
            <>
              <div className="flex justify-between text-[14px]"><span>Handler proposed</span><b className="num">{money(s.proposed_settlement, cur)}</b></div>
              <div className="flex justify-between text-[14px]"><span>Recalculated</span><b className="num">{money(s.payable, cur)}</b></div>
              <Alert className="!mt-3" showIcon type={diff && Math.abs(diff) > 0.5 ? 'error' : 'success'}
                message={diff && diff > 0.5 ? `Overpayment of ${money(diff, cur)} if paid as proposed`
                  : diff && diff < -0.5 ? `Underpayment of ${money(-diff, cur)} against the recalculation` : 'Proposed settlement matches the recalculation'} />
            </>
          )}
        </section>
        <section className="card rise p-5">
          <h3 className="m-0 mb-2 text-[15px] font-semibold">How it was calculated</h3>
          <ol className="m-0 space-y-1 pl-5 text-[13px]">
            {s.steps.map((step, i) => <li key={i} className="mono">{step}</li>)}
          </ol>
          <div className="muted mt-2 text-[12px]">Only calculated findings reduce the payable amount. Suspected ones wait for a reviewer.</div>
        </section>
      </div>
    </div>
  )
}
