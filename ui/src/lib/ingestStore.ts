import { useSyncExternalStore } from 'react'
import type { IngestResult } from '../api/types'

// Lives outside the page component, so the last ingest report and a running batch's progress survive navigating away.
interface IngestState {
  result: IngestResult | null
  progress: { done: number; total: number } | null
}

let state: IngestState = { result: null, progress: null }
const listeners = new Set<() => void>()

export const ingestStore = {
  get: (): IngestState => state,
  set(next: Partial<IngestState>) {
    state = { ...state, ...next }
    listeners.forEach((l) => l())
  },
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  },
}

export const useIngestState = (): IngestState => useSyncExternalStore(ingestStore.subscribe, ingestStore.get)
