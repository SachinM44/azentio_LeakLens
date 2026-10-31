import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Button, Empty, Segmented, Skeleton, Steps, Tabs, Tag, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Play } from 'lucide-react'
import { api, connection } from '../api/client'
import type { ClaimDetail, Run } from '../api/types'
import { Avatar } from '../components/ui'
import CaseRail from '../components/claim/CaseRail'
import DocumentComparisonTab from '../components/claim/DocumentComparisonTab'
import RelatedClaimsTab from '../components/claim/RelatedClaimsTab'
import TimelineTab from '../components/claim/TimelineTab'
import ClassificationTab from '../components/claim/ClassificationTab'
import DocumentsTab from '../components/claim/DocumentsTab'
import MasterDataTab from '../components/claim/MasterDataTab'
import SettlementTab from '../components/claim/SettlementTab'
import ErrorBox from '../components/ErrorBox'
import EvidenceDrawer, { type EvidenceRef } from '../components/EvidenceDrawer'
import FindingCard from '../components/FindingCard'
import { buildComparison } from '../lib/analysis'
import { currentDecision, type DecisionKind } from '../lib/decisions'
import { useRelated } from '../lib/useRelated'
import { SEVERITY_COLOR, fmtDate, money, pct, titleCase } from '../lib/format'
import { isActive } from '../lib/runs'

const STEP_LABEL: Record<string, string> = {
  load_master: 'Load record', classification_gate: 'Classification review', run_checks: 'Run checks', assess: 'Assess',
  settle: 'Settle', review_gate: 'Findings review', done: 'Done',
}

function RunPanel({ run, onRun, running }: { run: Run | null; onRun: () => void; running: boolean }) {
  const steps = run?.steps ?? []
  const status = (s: string): 'wait' | 'process' | 'finish' | 'error' =>
    s === 'running' ? 'process' : s === 'completed' || s === 'done' ? 'finish' : s === 'failed' || s === 'error' ? 'error' : s === 'paused' ? 'process' : 'wait'
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[13px]">
          <b>Workflow</b>{' '}
          <Tag className="!ml-1" color={run?.status === 'failed' ? 'red' : run?.status === 'paused' ? 'gold' : isActive(run) ? 'processing' : 'default'}>
            {run && run.status !== 'not_run' ? titleCase(run.status) : 'Not run'}
          </Tag>
          {run?.paused_at && <span className="muted">waiting at {STEP_LABEL[run.paused_at] ?? run.paused_at}</span>}
          {run && run.cost_usd > 0 && <span className="muted ml-2">model cost ${run.cost_usd.toFixed(3)}</span>}
        </div>
        <Button type="primary" size="small" icon={<Play size={13} />} loading={running} onClick={onRun}>{steps.length ? 'Re-run checks' : 'Run checks'}</Button>
      </div>
      {steps.length > 0 && (
        <Steps size="small" className="!mt-3" items={steps.map((s) => ({ title: STEP_LABEL[s.name] ?? s.name, status: status(s.status), description: s.error ? <span className="text-red-600">{s.error}</span> : undefined }))} />
      )}
      {run?.error && <Alert className="!mt-3" type="error" showIcon message="Run failed" description={run.error} />}
    </div>
  )
}

export default function ClaimDetailPage() {
  const { claimId = '' } = useParams()
  const qc = useQueryClient()
  const [tab, setTab] = useState('findings')
  const [filter, setFilter] = useState<'all' | 'open' | 'reviewed'>('all')
  const [highlight, setHighlight] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null)

  const detail = useQuery({ queryKey: ['claim', claimId], queryFn: () => api.getClaim(claimId) })
  const run = useQuery({
    queryKey: ['run', claimId], queryFn: () => api.getRun(claimId), initialData: undefined,
    refetchInterval: (q) => (isActive(q.state.data) ? 1000 : false),
  })
  const liveRun = run.data ?? detail.data?.run ?? null
  const notesQ = useQuery({ queryKey: ['notes', claimId], queryFn: () => api.listNotes(claimId) })
  const related = useRelated(detail.data)

  // When a run finishes, refresh everything that depends on its output.
  const wasActive = useActiveEdge(isActive(liveRun))
  useEffect(() => { if (wasActive === 'ended') { qc.invalidateQueries({ queryKey: ['claim', claimId] }); qc.invalidateQueries({ queryKey: ['claims'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) } }, [wasActive, claimId, qc])

  const start = useMutation({
    mutationFn: () => api.runClaim(claimId),
    onSuccess: () => { run.refetch() },
    onError: (e: Error) => message.error(e.message),
  })

  const review = useMutation({
    mutationFn: (v: { findingId: string; kind: DecisionKind; reason?: string; text?: string; amount?: number }) =>
      api.decide(claimId, v.findingId, { kind: v.kind, reason: v.reason, text: v.text, amount: v.amount }),
    onMutate: (v) => setReviewing(v.findingId),
    onSuccess: (res) => {
      qc.setQueryData<ClaimDetail>(['claim', claimId], (cur) => (cur ? { ...cur, findings: res.findings, settlement: res.settlement ?? cur.settlement, summary: res.summary ?? cur.summary } : cur))
      qc.invalidateQueries({ queryKey: ['claim', claimId] })
      qc.invalidateQueries({ queryKey: ['claims'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['eval'] })
      if (res.run_id) run.refetch()
      message.success('Decision recorded and added to the audit trail')
    },
    onError: (e: Error) => message.error(e.message),
    onSettled: () => setReviewing(null),
  })

  if (detail.isError) return <ErrorBox error={detail.error} onRetry={() => detail.refetch()} />
  if (!detail.data) return <Skeleton active paragraph={{ rows: 10 }} />

  const d = detail.data
  const { claim, summary } = d
  const open = d.findings.filter((f) => f.status === 'open')
  const shown = d.findings.filter((f) => (filter === 'open' ? f.status === 'open' : filter === 'reviewed' ? f.status !== 'open' : true))
  const awaitingClass = d.classification.some((c) => !c.confirmed_type)
  const notes = notesQ.data?.notes ?? []
  const diffCount = buildComparison(d).filter((r) => r.status !== 'match').length
  const escalated = d.findings.filter((f) => ['escalate_senior', 'escalate_siu'].includes(currentDecision(f)?.decision ?? ''))
  const awaitingEvidence = d.findings.filter((f) => currentDecision(f)?.decision === 'request_evidence')
  const relatedForReport = related.map((r) => ({ claim_id: r.claim_id, matches: r.matches }))

  const openTab = (key: string, line?: string) => { if (line) setHighlight(line); setTab(key); window.scrollTo({ top: 0 }) }
  const openEvidence = (source: string, ref: string, quote?: string) => {
    if (source === 'invoice_line' && d.lines.some((l) => l.line_id === ref)) { setEvidence({ source, ref, quote }); return }
    setEvidence({ source, ref, quote })
  }

  const findingsTab = (
    <div className="flex flex-col gap-3">
      {d.findings.length > 0 && (
        <Segmented value={filter} onChange={(v) => setFilter(v as typeof filter)}
          options={[{ value: 'all', label: `All ${d.findings.length}` }, { value: 'open', label: `Open ${open.length}` }, { value: 'reviewed', label: `Reviewed ${d.findings.length - open.length}` }]} />
      )}
      {!d.findings.length && (
        <Empty description={liveRun && liveRun.status !== 'not_run'
          ? 'No leakage found. Similar-looking services were checked and left alone.' : 'The checks have not run on this claim yet.'} />
      )}
      {shown.map((f) => (
        <FindingCard key={f.finding_id} finding={f} detail={d} busy={reviewing === f.finding_id}
          onLineClick={(id) => openTab('master', id)}
          onEvidenceClick={(source, ref) => openEvidence(source, ref, f.evidence.find((e) => e.ref === ref)?.quote)}
          onDecide={(kind, input) => review.mutate({ findingId: f.finding_id, kind, ...input })} />
      ))}
    </div>
  )

  return (
    <div className="flex flex-col gap-4">
      <section className="hero rise p-7">
        <Link to="/claims" className="inline-flex items-center gap-1 text-[13px] text-white/60 no-underline hover:text-accent"><ArrowLeft size={14} /> Back to claims</Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-6">
          <div className="flex items-center gap-4">
            <Avatar text={summary.claimant} size={56} />
            <div>
              <h1 className="mono m-0 text-[28px] font-semibold tracking-tight text-white">{claim.claim_id}</h1>
              <div className="mt-1 text-[13.5px] text-white/65">
                {claim.provider_name || claim.provider_id} · {titleCase(claim.claim_type)} · incident {fmtDate(claim.incident_date)}
                {claim.diagnosis ? ` · ${claim.diagnosis}` : ''}
              </div>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <span className="hero-chip">{titleCase(claim.status)}</span>
                <span className="hero-chip"><span className="inline-block h-2 w-2 rounded-full" style={{ background: summary.severity ? SEVERITY_COLOR[summary.severity] : '#9aa6b2' }} /> {summary.severity ? `${titleCase(summary.severity)} severity` : 'No severity'}</span>
                <span className="hero-chip">{d.findings.length} finding{d.findings.length === 1 ? '' : 's'}{open.length ? ` · ${open.length} open` : ''}</span>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="glass min-w-[140px] p-4"><div className="text-[12px] text-white/60">Requested</div>
              <div className="num text-[20px] font-semibold">{money(claim.requested_amount, claim.currency)}</div></div>
            <div className="glass min-w-[140px] p-4"><div className="text-[12px] text-white/60">Calculated leakage</div>
              <div className="num text-[20px] font-semibold" style={{ color: '#55ffbe' }}>{money(summary.leakage_calculated, claim.currency)}</div></div>
            <div className="glass min-w-[140px] p-4"><div className="text-[12px] text-white/60">Suspected</div>
              <div className="num text-[20px] font-semibold" style={{ color: '#ffd95e' }}>{money(summary.leakage_suspected, claim.currency)}</div></div>
          </div>
        </div>
        {claim.requested_amount > 0 && (summary.leakage_calculated > 0 || summary.leakage_suspected > 0) && (
          <div className="mt-5">
            <div className="flex h-2.5 overflow-hidden rounded-full bg-white/15">
              <div style={{ width: `${Math.min(100, (summary.leakage_calculated / claim.requested_amount) * 100)}%`, background: '#55ffbe' }} />
              <div style={{ width: `${Math.min(100, (summary.leakage_suspected / claim.requested_amount) * 100)}%`, background: '#ffd95e', opacity: 0.8 }} />
            </div>
            <div className="mt-1.5 text-[11.5px] text-white/55">
              {pct(Math.min(1, summary.leakage_calculated / claim.requested_amount))} of the requested amount is calculated leakage
              {summary.leakage_suspected > 0 ? `, a further ${pct(Math.min(1, summary.leakage_suspected / claim.requested_amount))} is suspected` : ''}
            </div>
          </div>
        )}
      </section>

      <RunPanel run={liveRun} running={start.isPending || isActive(liveRun)} onRun={() => start.mutate()} />

      {awaitingClass && (
        <Alert type="warning" showIcon message="Document classification needs your confirmation"
          action={<Button size="small" onClick={() => setTab('classification')}>Review pages</Button>} />
      )}

      {(escalated.length > 0 || awaitingEvidence.length > 0) && (
        <Alert type="info" showIcon
          message={[escalated.length ? `${escalated.length} finding${escalated.length === 1 ? '' : 's'} escalated` : '', awaitingEvidence.length ? `${awaitingEvidence.length} waiting for additional evidence` : ''].filter(Boolean).join(' · ')}
          description="These stay on the case file until the senior reviewer, the SIU or the provider responds." />
      )}

      {/* Full-width tab bar so every tab is visible; the content and the case rail sit below it. */}
      <Tabs data-tour="tabs" activeKey={tab} onChange={setTab} className="level2-tabs !mb-0" items={[
        { key: 'findings', label: `Findings${open.length ? ` (${open.length} open)` : ''}` },
        { key: 'related', label: `Related claims${related.length ? ` (${related.length})` : ''}` },
        { key: 'comparison', label: `Doc comparison${diffCount ? ` (${diffCount})` : ''}` },
        { key: 'settlement', label: 'Settlement' },
        { key: 'master', label: 'Master data' },
        { key: 'documents', label: `Documents (${d.documents.length})` },
        { key: 'classification', label: 'Classification' },
        { key: 'timeline', label: 'Audit trail' },
      ]} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {tab === 'findings' && findingsTab}
          {tab === 'related' && <RelatedClaimsTab detail={d} related={related} />}
          {tab === 'comparison' && <DocumentComparisonTab detail={d} onOpenDocuments={() => openTab('documents')} />}
          {tab === 'settlement' && <SettlementTab settlement={d.settlement} />}
          {tab === 'master' && <MasterDataTab detail={d} highlightLine={highlight} />}
          {tab === 'documents' && <DocumentsTab documents={d.documents} />}
          {tab === 'classification' && <ClassificationTab claimId={claimId} rows={d.classification} documentCount={d.documents.length} />}
          {tab === 'timeline' && <TimelineTab detail={d} notes={notes} related={relatedForReport} analyst={connection.analyst} />}
        </div>
        <CaseRail detail={d} notes={notes} notesLocal={!!notesQ.data?.local} onOpenEvidence={openEvidence} />
      </div>

      <EvidenceDrawer evidence={evidence} detail={d} onClose={() => setEvidence(null)} onOpenTab={openTab} />
    </div>
  )
}

/** Returns 'ended' on the render where `active` flips from true to false. */
function useActiveEdge(active: boolean): 'ended' | 'idle' {
  const [prev, setPrev] = useState(active)
  const [edge, setEdge] = useState<'ended' | 'idle'>('idle')
  useEffect(() => {
    setEdge(prev && !active ? 'ended' : 'idle')
    setPrev(active)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  return edge
}
