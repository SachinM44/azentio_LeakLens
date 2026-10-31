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

const PARALLEL_RUNS = 8

/** Run claims a few at a time (each runs in the background on the server); reports progress after every claim. */
export async function runMany(
  claimIds: string[],
  onProgress: (done: number, total: number, failed: string[]) => void,
): Promise<{ failed: string[] }> {
  const failed: string[] = []
  let next = 0
  let done = 0
  const worker = async () => {
    while (next < claimIds.length) {
      const id = claimIds[next++]
      try {
        const run = await runAndWait(id, { timeoutMs: 300_000 })
        if (run.status === 'failed' || run.error) failed.push(id)
      } catch {
        failed.push(id)
      }
      done += 1
      onProgress(done, claimIds.length, [...failed])
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALLEL_RUNS, claimIds.length) }, worker))
  return { failed }
}
