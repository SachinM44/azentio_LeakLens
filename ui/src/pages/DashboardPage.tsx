import { useNavigate } from 'react-router-dom'
import { Alert, Skeleton, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Calculator, ClipboardCheck, FileCheck2, FileSearch, HelpCircle, ArrowRight, ShieldCheck, Trophy, UploadCloud, Wallet } from 'lucide-react'
import { api } from '../api/client'
import type { CheckCategory, Dashboard, EvalSummary } from '../api/types'
import ErrorBox from '../components/ErrorBox'
import FilterBar from '../components/FilterBar'
import { CountUp, Donut, Panel, Ring, StatCard } from '../components/ui'
import { CATEGORY_COLOR, CATEGORY_LABEL, SEVERITY_COLOR, checkLabel, money, pct, titleCase } from '../lib/format'
import { useFilters } from '../lib/filters'

const compact = (n: number, cur: string) => {
  const sym = cur === 'INR' ? '₹' : cur === 'AED' ? 'AED ' : `${cur} `
  if (cur === 'INR' && n >= 1e7) return `${sym}${(n / 1e7).toFixed(2)} Cr`
  if (cur === 'INR' && n >= 1e5) return `${sym}${(n / 1e5).toFixed(2)} L`
  return money(Math.round(n), cur)
}

interface BarRow { key: string; label: string; count: number; calculated: number; suspected: number; color: string }

/** Calculated and suspected amounts are drawn as separate segments and never summed into one bar. */
function Bars({ rows, currency }: { rows: BarRow[]; currency: string }) {
  const max = Math.max(1, ...rows.map((r) => r.calculated + r.suspected))
  if (!rows.length) return <div className="muted py-6 text-center text-[13px]">No findings yet.</div>
  return (
    <div className="flex flex-col gap-4">
      {rows.map((r) => (
        <div key={r.key}>
          <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="font-medium">{r.label} <span className="muted font-normal">· {r.count}</span></span>
            <span className="num text-slate-600">
              {money(r.calculated, currency)}{r.suspected > 0 && <span className="text-amber-600"> + {money(r.suspected, currency)}</span>}
            </span>
          </div>
          <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div className="rounded-full transition-all duration-700" style={{ width: `${(r.calculated / max) * 100}%`, background: r.color }} />
            <div className="transition-all duration-700" style={{ width: `${(r.suspected / max) * 100}%`, background: r.color, opacity: 0.35 }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function Score({ data }: { data?: EvalSummary }) {
  if (!data) return <Skeleton active paragraph={{ rows: 3 }} />
  if (!data.available) return <Alert type="info" showIcon message="Score not available" description={data.reason ?? 'The answer key was not found on the server.'} />
  return (
    <div className="flex flex-col gap-5">
      <div className="flex justify-around">
        <Ring value={data.overall.precision} label="Precision" />
        <Ring value={data.overall.recall} label="Recall" color="#16303d" />
        <Ring value={data.amount_planted ? data.amount_recovered / data.amount_planted : null} label="Amount recovered" color="#ffc107" />
      </div>
      <div className="rounded-xl bg-slate-50 p-3 text-[12.5px] text-slate-600">
        <b>{data.overall.tp}</b> of {data.planted} planted issues found · {data.overall.fp} false alarms · {data.overall.fn} missed<br />
        {money(data.amount_recovered)} of {money(data.amount_planted)} recovered
      </div>
      {data.look_alikes_wrongly_flagged.length > 0 ? (
        <Alert type="warning" showIcon message={`${data.look_alikes_wrongly_flagged.length} legitimate look-alike(s) wrongly flagged`}
          description={data.look_alikes_wrongly_flagged.map((l) => `${l.claim_id} (${checkLabel(l.check_id)})`).join(', ')} />
      ) : (
        <Alert type="success" showIcon message={`All ${data.must_not_flag} legitimate look-alikes left alone`} />
      )}
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(data.by_check).map(([check, r]) => (
          <Tag key={check} color={(r.recall ?? 1) >= 0.9 && (r.precision ?? 1) >= 0.9 ? 'green' : 'orange'} className="!m-0">
            {checkLabel(check)} · P {pct(r.precision)} / R {pct(r.recall)}
          </Tag>
        ))}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const nav = useNavigate()
  const { filters, patch } = useFilters()
  const dash = useQuery({ queryKey: ['dashboard', filters], queryFn: () => api.dashboard(filters) })
  const score = useQuery({ queryKey: ['eval'], queryFn: api.evalSummary, retry: false })
  // The dashboard payload carries no currency, so take the most common one among the filtered claims (shares the Claims cache).
  const claims = useQuery({ queryKey: ['claims', filters], queryFn: () => api.listClaims(filters) })
  const currency = (() => {
    const counts: Record<string, number> = {}
    ;(claims.data ?? []).forEach((c) => { counts[c.currency] = (counts[c.currency] ?? 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'INR'
  })()
  const d: Dashboard | undefined = dash.data
  const drill = (category: string) => { patch({ category }); nav('/claims') }

  return (
    <div className="flex flex-col gap-6">
      <section data-tour="hero" className="hero rise p-8">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-xl">
            <div className="eyebrow">Claims leakage detection</div>
            <h1 className="mb-2 mt-2 text-[30px] font-semibold leading-tight tracking-tight text-white">
              {d ? <>Found <span className="text-mint-bright" style={{ color: '#55ffbe' }}><CountUp value={d.leakage_calculated} format={(n) => compact(n, currency)} /></span> of avoidable payout</> : 'Leakage overview'}
            </h1>
            <p className="m-0 text-[14px] leading-relaxed text-white/70">
              Every claim is checked against its policy, duplicates and settlement rules. Calculated amounts are exact by rule; suspected ones wait for a reviewer.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="hero-chip"><span className="live-dot" /> {d ? `${d.processed} of ${d.claims} claims processed` : 'Loading…'}</span>
              {d && d.awaiting_review > 0 && <span className="hero-chip"><ClipboardCheck size={13} /> {d.awaiting_review} awaiting review</span>}
            </div>
          </div>
          {d && (
            <div className="grid grid-cols-2 gap-3">
              <div className="glass min-w-[170px] p-4">
                <div className="text-[12px] text-white/60">Calculated</div>
                <div className="num text-[22px] font-semibold"><CountUp value={d.leakage_calculated} format={(n) => money(Math.round(n), currency)} /></div>
                <div className="text-[11px] text-white/50">exact, by rule</div>
              </div>
              <div className="glass min-w-[170px] p-4">
                <div className="text-[12px] text-white/60">Suspected</div>
                <div className="num text-[22px] font-semibold" style={{ color: '#ffd95e' }}><CountUp value={d.leakage_suspected} format={(n) => money(Math.round(n), currency)} /></div>
                <div className="text-[11px] text-white/50">pattern, needs a human</div>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="card rise p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="m-0 text-[15px] font-semibold">How LeakLens works</h2>
          <span className="muted text-[12px]">Click a step to open it</span>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          {[
            { icon: <UploadCloud size={18} />, n: '1', title: 'Ingest', text: 'Upload claims, policies and bills. Bad rows are reported.', path: '/ingest' },
            { icon: <FileSearch size={18} />, n: '2', title: 'Check', text: 'Rules test every line for duplicates, limits and exclusions.', path: '/claims' },
            { icon: <ShieldCheck size={18} />, n: '3', title: 'Review', text: 'A person confirms, corrects or dismisses each finding.', path: '/claims' },
            { icon: <Wallet size={18} />, n: '4', title: 'Settle', text: 'The payout is recalculated and the decision is audited.', path: '/claims' },
          ].map((s, i) => (
            <button key={s.n} type="button" onClick={() => nav(s.path)}
              className="relative cursor-pointer rounded-2xl border border-slate-200 bg-white p-4 text-left transition hover:border-accent hover:bg-mint/50">
              <div className="flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-mint text-brand">{s.icon}</span>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Step {s.n}</span>
              </div>
              <div className="mt-2 text-[15px] font-semibold">{s.title}</div>
              <div className="muted mt-0.5 text-[12.5px] leading-snug">{s.text}</div>
              {i < 3 && <ArrowRight size={16} className="absolute -right-3 top-1/2 z-10 hidden -translate-y-1/2 rounded-full bg-white text-slate-300 md:block" />}
            </button>
          ))}
        </div>
      </section>

      <FilterBar showStatus={false} />

      {dash.isError ? <ErrorBox error={dash.error} onRetry={() => dash.refetch()} /> : !d ? <Skeleton active paragraph={{ rows: 8 }} /> : (
        <>
          <div data-tour="stats" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard icon={<FileCheck2 size={19} />} label="Claims processed" color="#2ed88e" value={<CountUp value={d.processed} format={(n) => `${Math.round(n)}`} />}
              hint={`of ${d.claims} in view`} />
            <StatCard icon={<AlertTriangle size={19} />} label="Flagged claims" color="#dc3545" value={<CountUp value={d.flagged} format={(n) => `${Math.round(n)}`} />}
              hint={d.processed ? `${pct(d.flagged / d.processed)} of processed` : undefined} />
            <StatCard icon={<Calculator size={19} />} label="Calculated leakage" color="#16303d" value={compact(d.leakage_calculated, currency)} hint="exact, by rule" />
            <StatCard icon={<HelpCircle size={19} />} label="Suspected leakage" color="#f59e0b" value={compact(d.leakage_suspected, currency)} hint="needs a human decision" />
          </div>

          <div className="grid gap-6 lg:grid-cols-5">
            <Panel className="lg:col-span-3" title="Leakage by category" sub="Click a slice to open those claims">
              <Donut centre={d.by_category.reduce((s, c) => s + c.count, 0)} sub="findings"
                slices={d.by_category.map((c) => ({
                  key: c.category, label: CATEGORY_LABEL[c.category as CheckCategory] ?? titleCase(c.category), value: c.count,
                  color: CATEGORY_COLOR[c.category as CheckCategory] ?? '#94a3b8', onClick: () => drill(c.category),
                }))} />
              <div className="mt-6 border-t border-slate-100 pt-5">
                <Bars currency={currency} rows={d.by_category.map((c) => ({
                  key: c.category, label: CATEGORY_LABEL[c.category as CheckCategory] ?? titleCase(c.category), count: c.count,
                  calculated: c.amount_calculated, suspected: c.amount_suspected, color: CATEGORY_COLOR[c.category as CheckCategory] ?? '#94a3b8',
                }))} />
              </div>
            </Panel>
            <div className="flex flex-col gap-6 lg:col-span-2">
              <Panel title="Severity" sub="Findings by risk level">
                <div className="mb-4 flex h-3 overflow-hidden rounded-full bg-slate-100">
                  {d.by_severity.map((s) => (
                    <div key={s.severity} title={`${titleCase(s.severity)}: ${s.count}`} style={{ width: `${(s.count / Math.max(1, d.by_severity.reduce((a, b) => a + b.count, 0))) * 100}%`, background: SEVERITY_COLOR[s.severity] }} />
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {(['high', 'medium', 'low'] as const).map((sev) => {
                    const row = d.by_severity.find((s) => s.severity === sev)
                    return (
                      <div key={sev} className="rounded-xl p-3 text-center" style={{ background: `${SEVERITY_COLOR[sev]}14` }}>
                        <div className="num text-[22px] font-semibold" style={{ color: SEVERITY_COLOR[sev] }}>{row?.count ?? 0}</div>
                        <div className="text-[12px] text-slate-600">{titleCase(sev)}</div>
                        <div className="num text-[11px] text-slate-400">{compact(row?.amount ?? 0, currency)}</div>
                      </div>
                    )
                  })}
                </div>
              </Panel>
              <Panel title="Live score vs answer key" sub="Precision, recall and amount recovered">
                <Score data={score.isError ? { available: false, reason: (score.error as Error).message } : score.data} />
              </Panel>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="By check" sub="Which detectors are earning their keep">
              <Bars currency={currency} rows={d.by_check.slice(0, 7).map((c) => ({
                key: c.check_id, label: checkLabel(c.check_id), count: c.count, calculated: c.amount_calculated, suspected: c.amount_suspected, color: '#2ed88e',
              }))} />
            </Panel>
            <Panel title="Provider leaderboard" sub="Highest leakage first · click to filter claims"
              action={<Trophy size={18} className="text-amber-500" />}>
              <div className="flex flex-col gap-1">
                {d.by_provider.slice(0, 6).map((p, i) => {
                  const total = p.leakage_calculated + p.leakage_suspected
                  const top = d.by_provider[0] ? d.by_provider[0].leakage_calculated + d.by_provider[0].leakage_suspected : 1
                  return (
                    <button key={p.provider_id} type="button" onClick={() => { patch({ provider: p.provider_id }); nav('/claims') }}
                      className="flex cursor-pointer items-center gap-3 rounded-xl border-0 bg-transparent p-2.5 text-left transition hover:bg-mint/60">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[13px] font-semibold">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-[13.5px] font-medium">{p.provider_name}</span>
                          <span className="num text-[13px] font-semibold">{money(total, currency)}</span>
                        </span>
                        <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-slate-100">
                          <span className="block h-full rounded-full" style={{ width: `${(total / Math.max(1, top)) * 100}%`, background: 'linear-gradient(90deg,#2ed88e,#55ffbe)' }} />
                        </span>
                        <span className="muted mt-1 block text-[11.5px]">{p.flagged} of {p.claims} claims flagged</span>
                      </span>
                      <ArrowRight size={15} className="text-slate-300" />
                    </button>
                  )
                })}
                {!d.by_provider.length && <div className="muted py-6 text-center text-[13px]">No providers yet.</div>}
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
