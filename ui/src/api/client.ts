import type {
  AuditRow, ClaimDetail, ClaimFilters, ClaimSummary, ClassificationRow, Dashboard, EvalSummary, IngestResult,
  CaseNote, ProductConfig, ReviewResponse, Run,
} from './types'
import { DECISIONS, encodeNote, type DecisionKind } from '../lib/decisions'
import { mockRequest } from './mocks'

// ---- connection settings (editable from the header; kept per browser) -------------------------------------------

const KEY_URL = 'leaklens_api_url'
const KEY_API = 'leaklens_api_key'
const KEY_MOCK = 'leaklens_use_mocks'
const KEY_ANALYST = 'leaklens_analyst'
const KEY_NOTES = 'leaklens_local_notes'

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
  get useMocks(): boolean {
    const stored = read(KEY_MOCK)
    return stored !== null ? stored === 'true' : import.meta.env.VITE_USE_MOCKS === 'true'
  },
  /** Who is working the case; sent with every request and written into decisions and notes. */
  get analyst(): string {
    return read(KEY_ANALYST) || ''
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
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join('; ')
    return JSON.stringify(body)
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

async function request<T>(method: string, path: string, opts: { params?: Params; body?: unknown; form?: FormData } = {}): Promise<T> {
  if (connection.useMocks) return mockRequest<T>(method, path, opts.params ?? {}, opts.body, opts.form)
  const headers: Record<string, string> = { 'X-API-Key': connection.apiKey }
  if (connection.analyst) headers['X-Analyst'] = connection.analyst
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

const filterParams = (f: ClaimFilters): Params => ({ ...f })

// Claim notes: the backend has no notes endpoint yet, so a 404/405 falls back to this browser's storage.
type NoteStore = Record<string, CaseNote[]>
const readLocalNotes = (): NoteStore => {
  try { return JSON.parse(localStorage.getItem(KEY_NOTES) || '{}') as NoteStore } catch { return {} }
}
const writeLocalNotes = (all: NoteStore) => write(KEY_NOTES, JSON.stringify(all))
const noEndpoint = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 405 || e.status === 501)

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

  /** Record an analyst decision. It goes out as one of the backend's four actions with the decision tagged in the note. */
  decide: (claimId: string, findingId: string, v: { kind: DecisionKind; reason?: string; text?: string; amount?: number }) => {
    const meta = DECISIONS[v.kind]
    const body = {
      action: meta.backendAction,
      amount: v.kind === 'override_correction' ? v.amount : undefined,
      note: encodeNote(v.kind, connection.analyst, v.reason ?? '', v.text ?? ''),
    }
    return request<ReviewResponse>('POST', `/claims/${encodeURIComponent(claimId)}/findings/${encodeURIComponent(findingId)}/review`, { body })
  },

  async listNotes(claimId: string): Promise<{ notes: CaseNote[]; local: boolean }> {
    try {
      const notes = await request<CaseNote[]>('GET', `/claims/${encodeURIComponent(claimId)}/notes`)
      return { notes, local: false }
    } catch (e) {
      if (!noEndpoint(e)) throw e
      return { notes: readLocalNotes()[claimId] ?? [], local: true }
    }
  },

  async addNote(claimId: string, text: string): Promise<CaseNote> {
    const author = connection.analyst || 'analyst'
    try {
      return await request<CaseNote>('POST', `/claims/${encodeURIComponent(claimId)}/notes`, { body: { text, author } })
    } catch (e) {
      if (!noEndpoint(e)) throw e
      const note: CaseNote = { note_id: `N-${Date.now()}`, claim_id: claimId, author, text, ts: new Date().toISOString(), local: true }
      const all = readLocalNotes()
      all[claimId] = [...(all[claimId] ?? []), note]
      writeLocalNotes(all)
      return note
    }
  },

  dashboard: (filters: ClaimFilters) => request<Dashboard>('GET', '/dashboard', { params: filterParams(filters) }),
  listConfig: () => request<ProductConfig[]>('GET', '/config'),
  getConfig: (id: string) => request<ProductConfig>('GET', `/config/${encodeURIComponent(id)}`),
  putConfig: (id: string, config: ProductConfig) => request<ProductConfig>('PUT', `/config/${encodeURIComponent(id)}`, { body: config }),
  evalSummary: () => request<EvalSummary>('GET', '/eval/summary'),
  audit: (claimId?: string) => request<AuditRow[]>('GET', '/audit', { params: { claim_id: claimId } }),

  /** The document endpoint needs the API-key header, so an <img>/<iframe> src will not do: fetch it as a blob. */
  async documentBlob(id: string): Promise<Blob> {
    if (connection.useMocks) throw new ApiError(404, 'Documents are not available in mock mode')
    const res = await fetch(`${connection.baseUrl}/documents/${encodeURIComponent(id)}`, { headers: { 'X-API-Key': connection.apiKey } })
    if (!res.ok) throw new ApiError(res.status, await readError(res))
    return res.blob()
  },
}
