import type {
  AuditRow, ClaimDetail, ClaimFilters, ClaimSummary, ClassificationRow, Comparison, Dashboard, EvalSummary, IngestResult,
  Note, PortalStatus, PortalSubmitResponse, ProductConfig, RelatedResponse, ReviewBody, ReviewResponse, Run,
} from './types'
import { mockRequest } from './mocks'

// ---- connection settings (editable from the header; kept per browser) -------------------------------------------

const KEY_URL = 'leaklens_api_url'
const KEY_API = 'leaklens_api_key'
const KEY_MOCK = 'leaklens_use_mocks'
const KEY_ANALYST = 'leaklens_analyst'
export const DEFAULT_ANALYST = 'Claims analyst'

const read = (key: string): string | null => {
  try { return localStorage.getItem(key) } catch { return null }
}
const write = (key: string, value: string) => {
  try { localStorage.setItem(key, value) } catch { /* private mode */ }
}

export const connection = {
  get baseUrl(): string {
    return (read(KEY_URL) || import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
  },
  get apiKey(): string {
    return read(KEY_API) || import.meta.env.VITE_API_KEY || 'change-me'
  },
  // The screens always talk to the backend; mock data is only for UI development (VITE_USE_MOCKS=true).
  get useMocks(): boolean {
    return import.meta.env.VITE_USE_MOCKS === 'true'
  },
  /** The person acting: sent as X-Analyst so the audit log and decisions carry a name. */
  get analyst(): string {
    return (read(KEY_ANALYST) || '').trim() || DEFAULT_ANALYST
  },
  save(next: { baseUrl: string; apiKey: string; useMocks: boolean; analyst?: string }) {
    write(KEY_URL, next.baseUrl)
    write(KEY_API, next.apiKey)
    write(KEY_MOCK, String(next.useMocks))
    if (next.analyst !== undefined) write(KEY_ANALYST, next.analyst)
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | undefined | null>

function query(params?: Params): string {
  if (!params) return ''
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string; field?: string; problem?: string }) =>
        d.problem ? `${d.field ? `${d.field}: ` : ''}${d.problem}` : d.msg).join('; ')
    }
    return JSON.stringify(body)
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

async function request<T>(method: string, path: string, opts: { params?: Params; body?: unknown; form?: FormData } = {}): Promise<T> {
  if (connection.useMocks) return mockRequest<T>(method, path, opts.params ?? {}, opts.body, opts.form)
  const headers = authHeaders()
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(`${connection.baseUrl}${path}${query(opts.params)}`, { method, headers, body })
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${connection.baseUrl}. Is the backend running?`)
  }
  if (!res.ok) throw new ApiError(res.status, await readError(res))
  return (await res.json()) as T
}

function authHeaders(): Record<string, string> {
  return { 'X-API-Key': connection.apiKey, 'X-Analyst': connection.analyst }
}

async function fetchRaw(path: string, params?: Params): Promise<Response> {
  if (connection.useMocks) throw new ApiError(404, 'Not available in mock mode')
  let res: Response
  try {
    res = await fetch(`${connection.baseUrl}${path}${query(params)}`, { headers: authHeaders() })
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${connection.baseUrl}. Is the backend running?`)
  }
  if (!res.ok) throw new ApiError(res.status, await readError(res))
  return res
}

const filterParams = (f: ClaimFilters): Params => ({ ...f })

export const api = {
  health: () => request<{ status: string; store: string; ts: string }>('GET', '/health'),

  ingest: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f, f.name))
    return request<IngestResult>('POST', '/ingest', { form })
  },

  listClaims: (filters: ClaimFilters) => request<ClaimSummary[]>('GET', '/claims', { params: filterParams(filters) }),
  getClaim: (id: string) => request<ClaimDetail>('GET', `/claims/${encodeURIComponent(id)}`),
  runClaim: (id: string) => request<{ run_id: string; claim_id: string; status: string }>('POST', `/claims/${encodeURIComponent(id)}/run`),
  getRun: (id: string) => request<Run>('GET', `/claims/${encodeURIComponent(id)}/run`),

  classifyDocuments: (id: string) =>
    request<{ claim_id: string; classification: ClassificationRow[] }>('POST', `/claims/${encodeURIComponent(id)}/documents/classify`),

  confirmClassification: (id: string, pages: { page_id: string; document_type: string }[]) =>
    request<{ claim_id: string; classification: ClassificationRow[]; run_id: string | null }>(
      'POST', `/claims/${encodeURIComponent(id)}/classification/confirm`, { body: pages }),

  reviewFinding: (claimId: string, findingId: string, body: ReviewBody) =>
    request<ReviewResponse>('POST', `/claims/${encodeURIComponent(claimId)}/findings/${encodeURIComponent(findingId)}/review`, { body }),

  dashboard: (filters: ClaimFilters) => request<Dashboard>('GET', '/dashboard', { params: filterParams(filters) }),
  listConfig: () => request<ProductConfig[]>('GET', '/config'),
  getConfig: (id: string) => request<ProductConfig>('GET', `/config/${encodeURIComponent(id)}`),
  putConfig: (id: string, config: ProductConfig) => request<ProductConfig>('PUT', `/config/${encodeURIComponent(id)}`, { body: config }),
  evalSummary: () => request<EvalSummary>('GET', '/eval/summary'),
  audit: (claimId?: string) => request<AuditRow[]>('GET', '/audit', { params: { claim_id: claimId } }),

  addNote: (claimId: string, text: string) =>
    request<Note>('POST', `/claims/${encodeURIComponent(claimId)}/notes`, { body: { text } }),
  related: (claimId: string) => request<RelatedResponse>('GET', `/claims/${encodeURIComponent(claimId)}/related`),
  comparison: (claimId: string) => request<Comparison>('GET', `/claims/${encodeURIComponent(claimId)}/comparison`),

  /** The report needs the API-key header, so fetch it rather than linking to it. */
  async reportJson(claimId: string): Promise<Blob> {
    return (await fetchRaw(`/claims/${encodeURIComponent(claimId)}/report`, { format: 'json' })).blob()
  },
  async reportHtml(claimId: string): Promise<string> {
    return (await fetchRaw(`/claims/${encodeURIComponent(claimId)}/report`, { format: 'html' })).text()
  },

  portalSubmit: (form: FormData) => request<PortalSubmitResponse>('POST', '/portal/claims', { form }),
  portalStatus: (claimId: string) => request<PortalStatus>('GET', `/portal/claims/${encodeURIComponent(claimId)}`),

  /** The document endpoint needs the API-key header, so an <img>/<iframe> src will not do: fetch it as a blob. */
  async documentBlob(id: string): Promise<Blob> {
    if (connection.useMocks) throw new ApiError(404, 'Documents are not available in mock mode')
    const res = await fetch(`${connection.baseUrl}/documents/${encodeURIComponent(id)}`, { headers: authHeaders() })
    if (!res.ok) throw new ApiError(res.status, await readError(res))
    return res.blob()
  },
}
