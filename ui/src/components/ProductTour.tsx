import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tour } from 'antd'
import type { TourProps, TourStepProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

// A missing element becomes a centred step (antd accepts `() => null`), so a slow page never breaks the tour.
const el = (selector: string): (() => HTMLElement) => () => document.querySelector(selector) as HTMLElement

interface Step { path: string; selector?: string; title: string; description: string; placement?: TourStepProps['placement'] }

/** A walkthrough across the pages. It navigates for the user and spotlights real elements on screen. */
export default function ProductTour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [current, setCurrent] = useState(0)
  const claims = useQuery({ queryKey: ['claims', {}], queryFn: () => api.listClaims({}), enabled: open })

  const sampleClaim = useMemo(() => {
    const list = claims.data ?? []
    return (list.find((c) => c.findings > 0) ?? list[0])?.claim_id
  }, [claims.data])
  const claimPath = sampleClaim ? `/claims/${encodeURIComponent(sampleClaim)}` : '/claims'

  const steps: Step[] = useMemo(() => [
    { path: '/dashboard', title: 'Welcome to LeakLens', description: 'This is a quick tour of how a claim goes from upload to a reviewed settlement. It takes about a minute, and you can leave at any time.' },
    { path: '/dashboard', selector: '[data-tour="nav"]', placement: 'right', title: 'Your workspace', description: 'Dashboard for the big picture, Claims for the review queue, Ingest to bring in data, Config for the rule book. The badge on Claims counts claims waiting for you.' },
    { path: '/dashboard', selector: '[data-tour="hero"]', placement: 'bottom', title: 'How much is leaking', description: 'The headline is the total the checks found, exact by rule. Suspected amounts are patterns that need a person, and are never mixed into the total.' },
    { path: '/dashboard', selector: '[data-tour="stats"]', placement: 'bottom', title: 'Key numbers', description: 'Claims processed, flagged claims, calculated leakage and suspected leakage. They react to the filters below.' },
    { path: '/dashboard', selector: '[data-tour="filters"]', placement: 'bottom', title: 'Slice it your way', description: 'Filter by claim type, provider, leakage category, amount range and date. The same filters apply on the Claims page.' },
    { path: '/claims', selector: '[data-tour="claims-table"]', placement: 'top', title: 'The review queue', description: 'Every claim with its leakage, severity and open findings. Red is calculated leakage, amber is suspected. Click a row to open it.' },
    { path: claimPath, selector: '[data-tour="claim-hero"]', placement: 'bottom', title: 'One claim, at a glance', description: 'Requested amount, calculated and suspected leakage, and how much of the claim they represent.' },
    { path: claimPath, selector: '[data-tour="finding"]', placement: 'top', title: 'Every finding is explained', description: 'Each card shows the rule applied, the calculation, the supporting records and the policy clause. A Calculated badge means exact by rule; Suspected means a human should look.' },
    { path: claimPath, selector: '[data-tour="review"]', placement: 'top', title: 'You decide', description: 'Confirm, correct the amount, dismiss, or request clarification. Every decision recalculates the settlement and is written to the audit log.' },
    { path: claimPath, selector: '[data-tour="tabs"]', placement: 'bottom', title: 'More on the claim', description: 'Settlement shows the recalculated payout against the proposed one. Master data shows invoice lines and policy terms. Documents, Classification and Audit complete the picture.' },
    { path: '/ingest', selector: '[data-tour="upload"]', placement: 'top', title: 'Bring in data', description: 'Drop CSV, Excel, JSON, PDFs or images. Every invalid row is listed with the reason, and nothing is dropped silently.' },
    { path: '/config', selector: '.hero', placement: 'bottom', title: 'The rule book', description: 'Non-payable items, near-duplicate tolerances, repeatable services and required documents live here, so rules change without code changes.' },
    { path: '/dashboard', selector: '[data-tour="search"]', placement: 'bottom', title: 'Jump anywhere', description: 'Press Ctrl+K, or type a claim ID here and press Enter, to open any page or claim. Use "Take a tour" to replay this walkthrough. You are all set.' },
  ], [claimPath])

  // Navigate first, then move the spotlight once the new page has rendered its elements.
  const goTo = (index: number) => {
    const step = steps[Math.max(0, Math.min(steps.length - 1, index))]
    nav(step.path)
    window.setTimeout(() => setCurrent(index), 320)
  }

  useEffect(() => { if (open) { setCurrent(0); nav('/dashboard') } }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const tourSteps: TourProps['steps'] = steps.map((s) => ({
    title: s.title, description: s.description, target: s.selector ? el(s.selector) : null, placement: s.placement,
  }))

  return (
    <Tour open={open} current={current} steps={tourSteps} onChange={goTo} onClose={onClose}
      indicatorsRender={(cur, total) => <span className="text-[12px] text-slate-500">{cur + 1} / {total}</span>}
      gap={{ offset: 6, radius: 14 }} />
  )
}
