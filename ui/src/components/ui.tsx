import { useEffect, useRef, useState, type ReactNode } from 'react'

/** Animated count-up for headline numbers. */
export function CountUp({ value, format, duration = 900 }: { value: number; format: (n: number) => string; duration?: number }) {
  const [shown, setShown] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    const start = performance.now()
    const begin = from.current
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(begin + (value - begin) * eased)
      if (t < 1) raf = requestAnimationFrame(tick)
      else from.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{format(shown)}</>
}

export function Avatar({ text, size = 36, tone = 'mint' }: { text: string; size?: number; tone?: 'mint' | 'navy' }) {
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold"
      style={{ width: size, height: size, fontSize: size * 0.36, background: tone === 'mint' ? '#ddfff2' : '#16303d', color: tone === 'mint' ? '#16303d' : '#55ffbe' }}>
      {text}
    </span>
  )
}

/** Icon in a soft tinted circle, used on tiles and empty states. */
export function IconBubble({ children, color = '#2ed88e', size = 40 }: { children: ReactNode; color?: string; size?: number }) {
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-2xl" style={{ width: size, height: size, background: `${color}22`, color }}>
      {children}
    </span>
  )
}

export function StatCard({ icon, label, value, hint, color = '#2ed88e', className = '', children }: {
  icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode; color?: string; className?: string; children?: ReactNode
}) {
  return (
    <div className={`card card-hover rise p-5 ${className}`}>
      <div className="flex items-start justify-between">
        <div className="text-[13px] font-medium text-slate-500">{label}</div>
        <IconBubble color={color} size={38}>{icon}</IconBubble>
      </div>
      <div className="num mt-2 text-[28px] font-semibold leading-tight tracking-tight">{value}</div>
      {hint && <div className="muted mt-1 text-[12px]">{hint}</div>}
      {children}
    </div>
  )
}

export function Panel({ title, sub, action, children, className = '' }: { title: string; sub?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card rise p-5 ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-[16px] font-semibold">{title}</h2>
          {sub && <div className="muted mt-0.5 text-[12.5px]">{sub}</div>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export interface DonutSlice { key: string; label: string; value: number; color: string; onClick?: () => void }

/** Donut chart in plain SVG; the centre shows a headline figure. */
export function Donut({ slices, centre, sub, size = 190 }: { slices: DonutSlice[]; centre: ReactNode; sub?: string; size?: number }) {
  const total = slices.reduce((s, x) => s + x.value, 0)
  const r = 70, c = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg viewBox="0 0 200 200" width={size} height={size} className="-rotate-90">
          <circle cx="100" cy="100" r={r} fill="none" stroke="#eef2f5" strokeWidth="20" />
          {total > 0 && slices.filter((s) => s.value > 0).map((s) => {
            const len = (s.value / total) * c
            const el = (
              <circle key={s.key} cx="100" cy="100" r={r} fill="none" stroke={s.color} strokeWidth="20" strokeLinecap="butt"
                strokeDasharray={`${Math.max(0, len - 3)} ${c}`} strokeDashoffset={-offset} style={{ cursor: s.onClick ? 'pointer' : 'default', transition: 'stroke-dasharray .6s ease' }}
                onClick={s.onClick} />
            )
            offset += len
            return el
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
          <div className="num text-[24px] font-semibold leading-none">{centre}</div>
          {sub && <div className="muted mt-1 text-[11px]">{sub}</div>}
        </div>
      </div>
      <ul className="m-0 min-w-[160px] flex-1 list-none space-y-2 p-0">
        {slices.map((s) => (
          <li key={s.key} onClick={s.onClick} className={`flex items-center justify-between gap-3 text-[13px] ${s.onClick ? 'cursor-pointer hover:opacity-80' : ''}`}>
            <span className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />{s.label}</span>
            <span className="num font-medium">{s.value}</span>
          </li>
        ))}
        {!slices.length && <li className="muted text-[13px]">No findings yet.</li>}
      </ul>
    </div>
  )
}

/** Circular gauge, 0..1. */
export function Ring({ value, label, color = '#2ed88e', size = 92 }: { value: number | null; label: string; color?: string; size?: number }) {
  const r = 38, c = 2 * Math.PI * r
  const v = value == null ? 0 : Math.max(0, Math.min(1, value))
  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" width={size} height={size} className="-rotate-90">
          <circle cx="50" cy="50" r={r} fill="none" stroke="#eef2f5" strokeWidth="9" />
          <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
            strokeDasharray={`${v * c} ${c}`} style={{ transition: 'stroke-dasharray .8s ease' }} />
        </svg>
        <div className="num absolute inset-0 flex items-center justify-center text-[18px] font-semibold">{value == null ? '—' : `${Math.round(v * 100)}%`}</div>
      </div>
      <div className="muted mt-1 text-[12px]">{label}</div>
    </div>
  )
}

export function Empty({ icon, title, text, action }: { icon: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <IconBubble size={56}>{icon}</IconBubble>
      <div className="mt-1 text-[16px] font-semibold">{title}</div>
      {text && <div className="muted max-w-md text-[13px]">{text}</div>}
      {action}
    </div>
  )
}
