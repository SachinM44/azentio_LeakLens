import { api } from '../api/client'
import type { Run } from '../api/types'

const ACTIVE = new Set(['queued', 'running'])
export const isActive = (run?: Run | null): boolean => !!run && ACTIVE.has(run.status)

/** Start the workflow for one claim and wait until it finishes or pauses at a human gate. */
export async function runAndWait(claimId: string, { timeoutMs = 120_000, intervalMs = 1000 } = {}): Promise<Run> {
  await api.runClaim(claimId)
  const deadline = Date.now() + timeoutMs
  for (;;) {
    await new Promise((r) => setTimeout(r, intervalMs))
    const run = await api.getRun(claimId)
    if (!isActive(run) && run.status !== 'not_run') return run
    if (Date.now() > deadline) return run
  }
}

/** Run claims one at a time (the backend runs each in the background); reports progress after every claim. */
export async function runMany(
  claimIds: string[],
  onProgress: (done: number, total: number, failed: string[]) => void,
): Promise<{ failed: string[] }> {
  const failed: string[] = []
  for (let i = 0; i < claimIds.length; i++) {
    try {
      const run = await runAndWait(claimIds[i])
      if (run.status === 'failed' || run.error) failed.push(claimIds[i])
    } catch {
      failed.push(claimIds[i])
    }
    onProgress(i + 1, claimIds.length, [...failed])
  }
  return { failed }
}
