import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ClaimFilters } from '../api/types'

interface Ctx {
  filters: ClaimFilters
  setFilters: (next: ClaimFilters) => void
  patch: (next: Partial<ClaimFilters>) => void
  clear: () => void
  activeCount: number
}

const FiltersContext = createContext<Ctx | null>(null)
const STORE = 'leaklens_filters'

function load(): ClaimFilters {
  try { return JSON.parse(sessionStorage.getItem(STORE) || '{}') } catch { return {} }
}

/** One filter state shared by the Claims table and the Dashboard, so the same slice is visible on both. */
export function FiltersProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<ClaimFilters>(load)
  useEffect(() => {
    try { sessionStorage.setItem(STORE, JSON.stringify(filters)) } catch { /* ignore */ }
  }, [filters])
  const value = useMemo<Ctx>(() => {
    const clean = (f: ClaimFilters) =>
      Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined && v !== null && v !== '')) as ClaimFilters
    return {
      filters, setFilters: (n) => setFilters(clean(n)), patch: (n) => setFilters((cur) => clean({ ...cur, ...n })),
      clear: () => setFilters({}), activeCount: Object.keys(clean(filters)).length,
    }
  }, [filters])
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>
}

export function useFilters(): Ctx {
  const ctx = useContext(FiltersContext)
  if (!ctx) throw new Error('useFilters outside FiltersProvider')
  return ctx
}
