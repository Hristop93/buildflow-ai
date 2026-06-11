// Thin fetch client. Requests go to the Vite dev proxy (same origin), so the
// httpOnly auth cookie rides along automatically. Errors surface as ApiError
// carrying the HTTP status and the parsed `detail` from FastAPI.

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    throw new ApiError(res.status, data?.detail ?? data)
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
}

// --- Types mirroring the backend payloads -----------------------------------
export interface User {
  id: number
  email: string
  full_name: string | null
  company: string | null
  role: string
}

export interface ProjectType {
  id: string
  name: string
}

export interface Project {
  id: number
  name: string
  project_type_id: string | null
  municipality_id: number | null
  tier: string
  status: string
}

export interface Summary {
  procedure_count: number
  total_days: number
  total_fees: number
}

export interface RouteStep {
  procedure_id: string
  name: string
  institution: string | null
  act: string | null
  start_day: number
  end_day: number
  duration_days: number
  is_critical: boolean
}

export interface FeeCitation {
  act_id: string
  title: string
  article: string | null
  valid_from: string | null
}

export interface FeeItem {
  fee_id: string
  procedure: string
  description: string | null
  basis: string
  basis_value: number
  rate: number
  amount: number
  citation: FeeCitation | null
}

export interface ScheduleNode {
  start: number
  end: number
  duration: number
  critical: boolean
  name?: string
  status?: string
}

export interface ScheduleData {
  nodes: Record<string, ScheduleNode>
  total_days: number
}

export interface RecalcResult {
  project_id: number
  tier: string
  version_no: number
  summary: Summary
  route: RouteStep[]
  fees: { items: FeeItem[]; total: number }
  schedule: ScheduleData
  economics: Economics
}

export interface NodePatchResult {
  version_no: number
  delta_days: number | null
  delta_irr_pp: number | null
  result: RecalcResult
}

export interface CashflowPoint {
  year: number
  fcf: number
  cumulative: number
}

export interface Economics {
  capex: number
  irr: number
  npv: number
  lcoe: number
  payback_years: number
  verdict: string
  cashflow: CashflowPoint[]
}

export interface SectionResponse<T = unknown> {
  section: string
  your_tier: string
  required_tier: string
  data: T
}
