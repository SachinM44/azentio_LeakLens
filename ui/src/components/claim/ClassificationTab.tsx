import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Progress, Select, Table, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { ClassificationRow } from '../../api/types'
import { DOCUMENT_TYPES, titleCase } from '../../lib/format'

/** Human gate 1: the model proposes a type for every page; nothing is read until a person confirms the table. */
export default function ClassificationTab({ claimId, rows, documentCount }: { claimId: string; rows: ClassificationRow[]; documentCount: number }) {
  const qc = useQueryClient()
  const initial = () => Object.fromEntries(rows.map((r) => [r.page_id, r.confirmed_type ?? r.predicted_type ?? 'other_documents']))
  const [choice, setChoice] = useState<Record<string, string>>(initial)
  useEffect(() => setChoice(initial()), [rows]) // eslint-disable-line react-hooks/exhaustive-deps

  const confirm = useMutation({
    mutationFn: () => api.confirmClassification(claimId, rows.map((r) => ({ page_id: r.page_id, document_type: choice[r.page_id] }))),
    onSuccess: () => { message.success('Classification confirmed'); qc.invalidateQueries({ queryKey: ['claim', claimId] }) },
    onError: (e: Error) => message.error(e.message),
  })

  const classify = useMutation({
    mutationFn: () => api.classifyDocuments(claimId),
    onSuccess: () => { message.success('Pages classified — check them and confirm'); qc.invalidateQueries({ queryKey: ['claim', claimId] }) },
    onError: (e: Error) => message.error(e.message),
  })

  if (!rows.length && !documentCount) return <Empty description="No scanned documents on this claim, so there is nothing to classify." />
  if (!rows.length) {
    return (
      <Empty description={`${documentCount} document(s) attached. The AI reads every page and proposes its document type; you confirm before anything is extracted.`}>
        <Button type="primary" loading={classify.isPending} onClick={() => classify.mutate()}>Classify pages with AI</Button>
      </Empty>
    )
  }
  const pending = rows.some((r) => !r.confirmed_type)

  return (
    <div className="flex flex-col gap-3">
      {pending
        ? <Alert type="warning" showIcon message="Waiting for you" description="Check the predicted type of each page (low-confidence pages are marked), correct any that are wrong, then confirm. The workflow continues once you do." />
        : <Alert type="success" showIcon message="Classification confirmed" />}
      <Table<ClassificationRow> size="small" rowKey="page_id" dataSource={rows} pagination={false} className="card overflow-hidden"
        columns={[
          { title: 'Document', dataIndex: 'document_name', render: (v: string | undefined, r) => <span className="mono text-[12px]">{v ?? r.document_id}</span> },
          { title: 'Page', dataIndex: 'page', width: 70 },
          { title: 'Predicted', dataIndex: 'predicted_type', render: (v?: string | null) => (v ? titleCase(v) : '—') },
          { title: 'Confidence', dataIndex: 'confidence', width: 160,
            render: (v?: number | null) => (v == null ? '—' : <Progress percent={Math.round(v * 100)} size="small" status={v < 0.7 ? 'exception' : 'normal'} />) },
          { title: 'Confirmed type', key: 'choice', width: 280,
            render: (_: unknown, r) => (
              <Select showSearch className="w-full" value={choice[r.page_id]} onChange={(v) => setChoice((c) => ({ ...c, [r.page_id]: v }))}
                options={DOCUMENT_TYPES.map((t) => ({ value: t, label: titleCase(t) }))} />) },
        ]} />
      <div><Button type="primary" loading={confirm.isPending} onClick={() => confirm.mutate()}>Confirm classification</Button></div>
    </div>
  )
}
