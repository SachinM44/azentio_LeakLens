import { useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Input, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { FileSearch, LayoutDashboard, ListChecks, Search, Settings, ShieldCheck, SlidersHorizontal, UploadCloud } from 'lucide-react'
import { api, connection } from './api/client'
import SettingsModal from './components/SettingsModal'
import { Avatar } from './components/ui'
import ClaimsPage from './pages/ClaimsPage'
import ClaimDetailPage from './pages/ClaimDetailPage'
import ConfigPage from './pages/ConfigPage'
import DashboardPage from './pages/DashboardPage'
import IngestPage from './pages/IngestPage'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, group: 'Overview' },
  { to: '/claims', label: 'Claims', icon: ListChecks, group: 'Work' },
  { to: '/ingest', label: 'Ingest', icon: UploadCloud, group: 'Work' },
  { to: '/config', label: 'Config', icon: SlidersHorizontal, group: 'Admin' },
]

const TITLES: Record<string, string> = { dashboard: 'Dashboard', claims: 'Claims', ingest: 'Ingest', config: 'Configuration' }

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [jump, setJump] = useState('')
  const nav = useNavigate()
  const loc = useLocation()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000, retry: false })
  const dash = useQuery({ queryKey: ['dashboard', {}], queryFn: () => api.dashboard({}), staleTime: 30_000 })
  const mock = connection.useMocks
  const awaiting = dash.data?.awaiting_review ?? 0

  const parts = loc.pathname.split('/').filter(Boolean)
  const section = TITLES[parts[0]] ?? 'LeakLens'
  const groups = Array.from(new Set(NAV.map((n) => n.group)))

  return (
    <div className="flex h-full">
      <aside className="flex w-[240px] shrink-0 flex-col text-white"
        style={{ background: 'linear-gradient(180deg, #0d1c4f 0%, #16303d 45%, #16303d 100%)' }}>
        <div className="flex items-center gap-3 px-6 pb-4 pt-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-2xl text-brand shadow-lg"
            style={{ background: 'linear-gradient(135deg, #55ffbe, #2ed88e)' }}><FileSearch size={21} /></span>
          <div className="leading-tight">
            <div className="text-[20px] font-semibold tracking-tight">LeakLens</div>
            <div className="text-[11px] text-white/50">Claims leakage agent</div>
          </div>
        </div>

        <nav className="mt-2 flex flex-col gap-5 px-4">
          {groups.map((g) => (
            <div key={g} className="flex flex-col gap-1">
              <div className="px-3 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/35">{g}</div>
              {NAV.filter((n) => n.group === g).map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to}
                  className={({ isActive }) =>
                    `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-medium no-underline transition-all ${
                      isActive ? 'bg-accent text-brand shadow-[0_8px_20px_-8px_rgba(46,216,142,0.7)]' : 'text-white/75 hover:bg-white/10 hover:text-white'}`}>
                  <Icon size={18} />
                  <span className="flex-1">{label}</span>
                  {to === '/claims' && awaiting > 0 && (
                    <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-semibold text-accent group-[.active]:bg-brand/10">{awaiting}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="mt-auto p-4">
          <div className="glass p-4">
            <div className="flex items-center gap-2 text-[12.5px] font-medium"><ShieldCheck size={15} className="text-accent" /> AI finds. Rules compute. Humans decide.</div>
            <div className="mt-2 text-[11.5px] leading-relaxed text-white/55">Every amount is calculated by rule and reviewed before settlement.</div>
          </div>
          <div className="mt-3 flex items-center justify-between px-1 text-[12px]">
            <span className="text-white/55">API</span>
            {mock ? <Tag color="gold" className="!m-0">Mock data</Tag>
              : health.isSuccess ? <Tag color="green" className="!m-0">Connected</Tag>
              : health.isLoading ? <Tag className="!m-0">Checking…</Tag> : <Tag color="red" className="!m-0">Offline</Tag>}
          </div>
          <button type="button" onClick={() => setSettingsOpen(true)}
            className="mt-2 flex w-full cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-transparent px-3 py-2 text-[13px] text-white/75 transition hover:border-accent hover:text-accent">
            <Settings size={14} /> Connection
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[68px] shrink-0 items-center justify-between gap-4 border-b border-slate-200/70 bg-white/80 px-8 backdrop-blur">
          <div className="flex items-center gap-2 text-[14px]">
            <span className="muted">LeakLens</span><span className="text-slate-300">/</span>
            <span className="font-semibold">{section}</span>
            {parts[1] && <><span className="text-slate-300">/</span><span className="mono text-[13px] font-medium">{decodeURIComponent(parts[1])}</span></>}
          </div>
          <div className="flex items-center gap-4">
            <Input allowClear prefix={<Search size={15} className="text-slate-400" />} placeholder="Jump to claim, e.g. CLM-1001"
              value={jump} onChange={(e) => setJump(e.target.value)} className="!w-72 !rounded-full"
              onPressEnter={() => { if (jump.trim()) { nav(`/claims/${encodeURIComponent(jump.trim().toUpperCase())}`); setJump('') } }} />
            <div className="flex items-center gap-2.5">
              <Avatar text="CH" tone="navy" size={38} />
              <div className="hidden leading-tight lg:block">
                <div className="text-[13px] font-semibold">Claims Handler</div>
                <div className="muted flex items-center gap-1.5 text-[11.5px]"><span className="live-dot" /> On duty</div>
              </div>
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1320px] px-8 py-7">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/claims" element={<ClaimsPage />} />
              <Route path="/claims/:claimId" element={<ClaimDetailPage />} />
              <Route path="/ingest" element={<IngestPage />} />
              <Route path="/config" element={<ConfigPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </div>
        </main>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
