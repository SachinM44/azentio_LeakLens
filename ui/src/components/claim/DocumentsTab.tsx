import { useEffect, useState } from 'react'
import { Alert, Empty, List, Spin, Tag } from 'antd'
import { FileText } from 'lucide-react'
import { api } from '../../api/client'
import type { DocumentView } from '../../api/types'
import { fmtDateTime, titleCase } from '../../lib/format'

export default function DocumentsTab({ documents }: { documents: DocumentView[] }) {
  const [selected, setSelected] = useState<DocumentView | null>(documents[0] ?? null)
  const [url, setUrl] = useState<string | null>(null)
  const [mime, setMime] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { if (!selected && documents.length) setSelected(documents[0]) }, [documents, selected])

  useEffect(() => {
    if (!selected) return
    let objectUrl: string | null = null
    let cancelled = false
    setLoading(true); setError(null); setUrl(null)
    api.documentBlob(selected.id)
      .then((blob) => { if (cancelled) return; objectUrl = URL.createObjectURL(blob); setMime(blob.type || selected.mime || ''); setUrl(objectUrl) })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [selected])

  if (!documents.length) return <Empty description="No documents are attached to this claim (structured upload)." />

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <List bordered size="small" className="!bg-white" dataSource={documents}
        renderItem={(d) => (
          <List.Item onClick={() => setSelected(d)} className={`cursor-pointer ${selected?.id === d.id ? '!bg-mint' : ''}`}>
            <div className="flex min-w-0 items-start gap-2">
              <FileText size={16} className="mt-0.5 shrink-0 text-slate-400" />
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium">{d.name ?? d.id}</div>
                <div className="muted text-[12px]">{d.pages} page{d.pages === 1 ? '' : 's'} · {fmtDateTime(d.uploaded_at)}</div>
                <Tag className="!mt-1 !mr-0">{d.type ? titleCase(d.type) : 'Unclassified'}</Tag>
              </div>
            </div>
          </List.Item>
        )} />
      <div className="min-h-[520px] card overflow-hidden bg-white">
        {loading && <div className="flex h-[520px] items-center justify-center"><Spin /></div>}
        {error && <Alert className="m-4" type="warning" showIcon message="Document could not be loaded" description={error} />}
        {url && (mime.startsWith('image/')
          ? <img src={url} alt={selected?.name} className="mx-auto max-h-[760px] max-w-full object-contain" />
          : <iframe src={url} title={selected?.name} className="h-[760px] w-full border-0" />)}
      </div>
    </div>
  )
}
