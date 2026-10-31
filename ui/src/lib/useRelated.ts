import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ClaimDetail, Finding } from '../api/types'
import { matchClaims, type Match } from './analysis'

export interface RelatedClaim {
  claim_id: string
  detail?: ClaimDetail
  loading: boolean
  failed: boolean
  matches: Match[]
  /** The findings on this claim that point at the related one: why the system connected them. */
  because: Finding[]
}

/** Claims connected to this one through the findings, with the attributes that connect them. */
export function useRelated(detail: ClaimDetail | undefined): RelatedClaim[] {
  const ids = useMemo(() => {
    if (!detail) return []
    return Array.from(new Set(detail.findings.flatMap((f) => f.related_claim_ids))).filter((id) => id !== detail.claim.claim_id)
  }, [detail])

  const results = useQueries({
    queries: ids.map((id) => ({ queryKey: ['claim', id], queryFn: () => api.getClaim(id), staleTime: 30_000 })),
  })

  return ids.map((id, i) => {
    const r = results[i]
    const other = r.data
    return {
      claim_id: id, detail: other, loading: r.isLoading, failed: r.isError,
      matches: other && detail ? matchClaims(detail.claim, other.claim) : [],
      because: detail ? detail.findings.filter((f) => f.related_claim_ids.includes(id)) : [],
    }
  })
}
