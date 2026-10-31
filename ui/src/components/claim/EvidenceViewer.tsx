import { useEffect, useState } from 'react'
import { Alert, Button, Modal, Spin, Table, Tag } from 'antd'
import { api } from '../../api/client'
import type { Comparison, ComparisonField, ComparisonLine, DocSource } from '../../api/types'
import { money, titleCase } from '../../lib/format'

const FIELD_COLOR: Record<string, string> = { match: 'green', mismatch: 'red', only_in_claim: 'gold', only_in_document: 'blue', not_read: 'default' }
const LINE_COLOR: Record<string, string> = { match: 'green', amount_differs: 'red', only_in_document: 'blue', only_in_claim: 'gold' }

interface Props {
  source: DocSource | null
  comparison: Comparison
  currency: string
  onClose: () => void
  onOpenDocuments: (documentId: string) => void
}

/** The document on the left (opened at the cited page) and, on the right, everything the AI read from that document
 * next to what the claim record says — so every extracted value can be checked against its source. */
export default function EvidenceViewer({ source, comparison, currency, onClose, onOpenDocuments }: Props) {
  const [url, setUrl] = useState<string | null>(null)
  const [mime, setMime] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!source) return
    let objectUrl: string | null = null
    let cancelled = false
    setUrl(null); setError(null)
    api.documentBlob(source.document_id)
      .then((blob) => { if (cancelled) return; objectUrl = URL.createObjectURL(blob); setMime(blob.type || ''); setUrl(objectUrl) })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [source])

  if (!source) return null
  const fromThisDoc = (s: DocSource | null) => !!s && s.document_id === source.document_id
  const fields = comparison.fields.filter((f) => fromThisDoc(f.source))
  const lines = comparison.lines.filter((l) => fromThisDoc(l.source))
  const page = source.page ?? 1

  return (
    <Modal open onCancel={onClose} width="94vw" style={{ top: 24 }} title={(
      <div className="flex flex-wrap items-center gap-2">
        <span>{source.document_name}</span>
        <Tag className="!m-0">page {page}</Tag>
        {comparison.extracted_by && <Tag color="green" className="!m-0">read by {comparison.extracted_by === 'ai-text' ? 'AI (text)' : 'AI (vision)'}</Tag>}
        {comparison.model && <span className="muted text-[12px]">{comparison.model.replace(/^bedrock\//, '')}{comparison.read_seconds ? ` · ${comparison.read_seconds} s` : ''}</span>}
      </div>
    )} footer={<Button onClick={() => { onOpenDocuments(source.document_id); onClose() }}>Open in Documents tab</Button>}>
      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <div className="card overflow-hidden bg-white" style={{ height: '74vh' }}>
          {error && <Alert className="m-4" type="warning" showIcon message="Document could not be loaded" description={error} />}
          {!url && !error && <div className="flex h-full items-center justify-center"><Spin /></div>}
          {url && (mime.startsWith('image/')
            ? <img src={url} alt={source.document_name} className="mx-auto h-full max-w-full object-contain" />
            : <iframe src={`${url}#page=${page}`} title={source.document_name} className="h-full w-full border-0" />)}
        </div>
        <div className="flex flex-col gap-4 overflow-auto" style={{ maxHeight: '74vh' }}>
          <div>
            <div className="eyebrow mb-2">Read from this document vs the claim record</div>
            <Table<ComparisonField> size="small" rowKey={(r) => r.field} dataSource={fields} pagination={false} className="card overflow-hidden"
              locale={{ emptyText: 'No header fields came from this document.' }}
              columns={[
                { title: 'Field', dataIndex: 'label' },
                { title: 'Extracted', dataIndex: 'document_value', render: (v) => <span className="font-medium">{v ?? '—'}</span> },
                { title: 'Claim record', dataIndex: 'claim_value', render: (v) => v ?? '—' },
                { title: 'Page', key: 'page', width: 60, render: (_: unknown, r) => r.source?.page ?? '—' },
                { title: '', dataIndex: 'status', width: 120, render: (s: string) => <Tag color={FIELD_COLOR[s]}>{titleCase(s)}</Tag> },
              ]} />
          </div>
          <div>
            <div className="eyebrow mb-2">Bill lines read from this document ({lines.length})</div>
            <Table<ComparisonLine> size="small" dataSource={lines} pagination={false} className="card overflow-hidden"
              rowKey={(r) => `${r.status}|${r.claim_line_id ?? ''}|${r.code ?? ''}|${r.description}|${r.document_amount ?? ''}`}
              locale={{ emptyText: 'No bill lines came from this document.' }}
              columns={[
                { title: 'Description', dataIndex: 'description', render: (v: string, r) => <span>{r.code ? <span className="mono muted mr-1 text-[11px]">{r.code}</span> : null}{v}</span> },
                { title: 'Extracted', dataIndex: 'document_amount', align: 'right', render: (v?: number | null) => (v == null ? '—' : money(v, currency)) },
                { title: 'Claim record', dataIndex: 'claim_amount', align: 'right', render: (v?: number | null) => (v == null ? '—' : money(v, currency)) },
                { title: 'Page', key: 'page', width: 60, render: (_: unknown, r) => r.source?.page ?? '—' },
                { title: '', dataIndex: 'status', width: 130, render: (s: string) => <Tag color={LINE_COLOR[s]}>{titleCase(s)}</Tag> },
              ]} />
          </div>
        </div>
      </div>
    </Modal>
  )
}
