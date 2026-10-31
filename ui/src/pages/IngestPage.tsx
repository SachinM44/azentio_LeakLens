import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Progress, Table, Tag, Upload, message } from 'antd'
import type { UploadFile } from 'antd/es/upload'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CloudUpload, Play } from 'lucide-react'
import { api } from '../api/client'
import type { IngestResult, ValidationIssue } from '../api/types'
import { titleCase } from '../lib/format'
import { runMany } from '../lib/runs'

const ACCEPT = '.csv,.xlsx,.xls,.json,.pdf,.jpg,.jpeg,.png'

export default function IngestPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [files, setFiles] = useState<UploadFile[]>([])
  const [result, setResult] = useState<IngestResult | null>(null)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)

  const ingest = useMutation({
    mutationFn: () => api.ingest(files.map((f) => f.originFileObj as File)),
    onSuccess: (r) => { setResult(r); setFiles([]); qc.invalidateQueries() },
    onError: (e: Error) => message.error(e.message),
  })

  const runAffected = async () => {
    if (!result) return
    const ids = result.claims_affected
    setProgress({ done: 0, total: ids.length })
    const { failed } = await runMany(ids, (done, total) => setProgress({ done, total }))
    setProgress(null)
    qc.invalidateQueries()
    if (failed.length) message.warning(`${failed.length} claim(s) failed to run`)
    nav('/claims')
  }

  const rejected = result?.validation.filter((v) => !v.accepted) ?? []
  const warnings = result?.validation.filter((v) => v.accepted) ?? []

  const issueColumns = [
    { title: 'File', dataIndex: 'file', ellipsis: true },
    { title: 'Row', dataIndex: 'row', width: 70, render: (v?: number | null) => v ?? '—' },
    { title: 'Field', dataIndex: 'field', width: 160, render: (v: string) => <span className="mono">{v || '—'}</span> },
    { title: 'Problem', dataIndex: 'problem' },
    { title: 'Outcome', dataIndex: 'accepted', width: 150,
      render: (v: boolean) => (v ? <Tag color="gold" className="!m-0">Accepted with warning</Tag> : <Tag color="red" className="!m-0">Rejected</Tag>) },
  ]

  return (
    <div className="flex flex-col gap-4">
      <section className="hero rise p-7">
        <div className="eyebrow">Data ingestion</div>
        <h1 className="mb-1 mt-1.5 text-[26px] font-semibold tracking-tight text-white">Bring in claims, policies and documents</h1>
        <p className="m-0 max-w-2xl text-[13.5px] text-white/65">
          CSV, Excel or JSON for claims, invoice lines, policies and history; PDF or images for scanned claim documents.
          Every invalid row is reported below, and nothing is dropped silently.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          {[['1', 'Upload files', !result], ['2', 'Review validation', !!result], ['3', 'Run checks', !!result && !!progress]].map(([n, label, active]) => (
            <span key={n as string} className="hero-chip" style={active ? { background: '#2ed88e', color: '#16303d', borderColor: '#2ed88e' } : undefined}>
              <b>{n}</b> {label}
            </span>
          ))}
        </div>
      </section>

      <Upload.Dragger multiple accept={ACCEPT} fileList={files} beforeUpload={() => false}
        onChange={({ fileList }) => setFiles(fileList)} className="!bg-white">
        <p className="flex justify-center text-accent"><CloudUpload size={38} /></p>
        <p className="text-[16px] font-medium">Drop files here or click to choose</p>
        <p className="muted text-[13px]">.csv · .xlsx · .json · .pdf · .jpg · .png — any mix in one batch</p>
      </Upload.Dragger>

      <div>
        <Button type="primary" size="large" loading={ingest.isPending} disabled={!files.length} onClick={() => ingest.mutate()}>
          Ingest {files.length || ''} file{files.length === 1 ? '' : 's'}
        </Button>
      </div>

      {result && (
        <div className="flex flex-col gap-4">
          <Alert type={rejected.length ? 'warning' : 'success'} showIcon
            message={`${result.claims_created} new claim${result.claims_created === 1 ? '' : 's'} created · ${result.claims_affected.length} claim${result.claims_affected.length === 1 ? '' : 's'} updated`}
            description={(
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {Object.entries(result.counts).map(([k, v]) => <Tag key={k} className="!m-0">{v} {titleCase(k)}</Tag>)}
                <span className="muted ml-1 text-[12px]">batch {result.batch_id}</span>
              </div>
            )}
            action={(
              <div className="flex items-center gap-2">
                {progress && <Progress type="circle" size={30} percent={Math.round((progress.done / progress.total) * 100)} />}
                <Button type="primary" icon={<Play size={14} />} loading={!!progress} disabled={!result.claims_affected.length} onClick={runAffected}>
                  Run checks on {result.claims_affected.length}
                </Button>
              </div>
            )} />

          <section className="card p-5">
            <h2 className="m-0 mb-1 text-[15px] font-semibold">Validation report</h2>
            <div className="muted mb-3 text-[12px]">{rejected.length} rejected · {warnings.length} accepted with a warning</div>
            <Table<ValidationIssue> size="small" rowKey={(r) => `${r.file}-${r.row}-${r.field}-${r.problem}`} columns={issueColumns}
              dataSource={result.validation} pagination={{ pageSize: 10, hideOnSinglePage: true }}
              locale={{ emptyText: 'Every row passed validation.' }} />
          </section>

          {result.documents.length > 0 && (
            <section className="card p-5">
              <h2 className="m-0 mb-2 text-[15px] font-semibold">Documents stored</h2>
              <ul className="m-0 list-none space-y-1 p-0 text-[13px]">
                {result.documents.map((d, i) => (
                  <li key={d.id ?? d.document_id ?? i}><span className="mono">{d.name ?? d.id ?? d.document_id}</span>
                    {d.pages ? ` · ${d.pages} page${d.pages === 1 ? '' : 's'}` : ''}{d.claim_id ? ` · claim ${d.claim_id}` : ''}</li>
                ))}
              </ul>
              <div className="muted mt-2 text-[12px]">Open the claim and use the Classification tab to confirm page types before the checks run.</div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
