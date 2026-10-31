import { useState } from 'react'
import { Button, Empty, Input, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { ClaimDetail, Note } from '../../api/types'
import { Avatar } from '../ui'
import { fmtDateTime } from '../../lib/format'

export default function NotesTab({ claimId, notes }: { claimId: string; notes: Note[] }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const add = useMutation({
    mutationFn: () => api.addNote(claimId, text.trim()),
    onSuccess: (note) => {
      qc.setQueryData<ClaimDetail>(['claim', claimId], (cur) => (cur ? { ...cur, notes: [note, ...(cur.notes ?? [])] } : cur))
      qc.invalidateQueries({ queryKey: ['claim', claimId] })
      setText('')
    },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4">
        <Input.TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note for this claim (kept in the audit log and the report)" />
        <div className="mt-2 flex justify-end">
          <Button type="primary" loading={add.isPending} disabled={!text.trim()} onClick={() => add.mutate()}>Add note</Button>
        </div>
      </div>
      {!notes.length && <Empty description="No notes yet." />}
      {notes.map((n) => (
        <div key={n.note_id} className="card flex items-start gap-3 p-4">
          <Avatar text={(n.author || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('')} size={34} />
          <div className="min-w-0">
            <div className="text-[13px]"><b>{n.author}</b> <span className="muted">· {fmtDateTime(n.ts)}</span></div>
            <div className="mt-1 whitespace-pre-wrap text-[14px]">{n.text}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
