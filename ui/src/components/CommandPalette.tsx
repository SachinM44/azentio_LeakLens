import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { CornerDownLeft, FileText, LayoutDashboard, ListChecks, Search, SlidersHorizontal, UploadCloud } from 'lucide-react'
import { api } from '../api/client'
import { money, titleCase } from '../lib/format'

interface Item { key: string; label: string; hint: string; icon: JSX.Element; path: string }

const PAGES: Item[] = [
  { key: 'p-dash', label: 'Dashboard', hint: 'Leakage overview', icon: <LayoutDashboard size={16} />, path: '/dashboard' },
  { key: 'p-claims', label: 'Claims', hint: 'Review queue', icon: <ListChecks size={16} />, path: '/claims' },
  { key: 'p-ingest', label: 'Ingest', hint: 'Upload data', icon: <UploadCloud size={16} />, path: '/ingest' },
  { key: 'p-config', label: 'Config', hint: 'Rule book', icon: <SlidersHorizontal size={16} />, path: '/config' },
]

/** Ctrl+K: jump to any page or claim from the keyboard. */
export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const claims = useQuery({ queryKey: ['claims', {}], queryFn: () => api.listClaims({}), enabled: open, staleTime: 15_000 })

  const items = useMemo(() => {
    const claimItems: Item[] = (claims.data ?? []).map((c) => ({
      key: c.claim_id, label: c.claim_id, icon: <FileText size={16} />, path: `/claims/${encodeURIComponent(c.claim_id)}`,
      hint: `${c.provider} · ${titleCase(c.claim_type)} · ${money(c.requested_amount, c.currency)}${c.findings ? ` · ${c.findings} finding${c.findings === 1 ? '' : 's'}` : ''}`,
    }))
    const needle = q.trim().toLowerCase()
    return [...PAGES, ...claimItems].filter((i) => !needle || `${i.label} ${i.hint}`.toLowerCase().includes(needle)).slice(0, 9)
  }, [claims.data, q])

  useEffect(() => { if (open) { setQ(''); setIdx(0); window.setTimeout(() => input.current?.focus(), 50) } }, [open])
  useEffect(() => setIdx(0), [q])

  const go = (item?: Item) => { if (item) { nav(item.path); onClose() } }

  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} width={560} styles={{ body: { padding: 0 } }} style={{ top: 110 }}>
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <Search size={18} className="text-slate-400" />
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search pages and claims…"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(items.length - 1, i + 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)) }
            else if (e.key === 'Enter') go(items[idx])
          }}
          className="flex-1 border-0 bg-transparent text-[15px] outline-none" />
        <kbd className="rounded-md border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-400">Esc</kbd>
      </div>
      <ul className="m-0 max-h-[360px] list-none overflow-y-auto p-2">
        {items.map((it, i) => (
          <li key={it.key} onMouseEnter={() => setIdx(i)} onClick={() => go(it)}
            className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 ${i === idx ? 'bg-mint' : ''}`}>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-brand">{it.icon}</span>
            <span className="min-w-0 flex-1"><span className="block text-[14px] font-medium">{it.label}</span><span className="muted block truncate text-[12px]">{it.hint}</span></span>
            {i === idx && <CornerDownLeft size={14} className="text-slate-400" />}
          </li>
        ))}
        {!items.length && <li className="muted py-8 text-center text-[13px]">Nothing matches “{q}”.</li>}
      </ul>
    </Modal>
  )
}
