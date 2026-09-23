import { useCallback, useEffect, useState } from 'react'

export type Lottery = 'ssq' | 'dlt' | 'qlc' | 'kl8' | 'fc3d' | 'pl3' | 'pl5' | 'qxc'
export const LOTTERY_NAME: Record<Lottery, string> = {
  ssq: '双色球',
  dlt: '大乐透',
  qlc: '七乐彩',
  kl8: '快乐8',
  fc3d: '福彩3D',
  pl3: '排列3',
  pl5: '排列5',
  qxc: '七星彩',
}
export const POOL_RESEARCH: Lottery[] = ['ssq', 'dlt', 'qlc', 'kl8']
export type DatasetKind = 'real' | 'synthetic'
export interface Scope {
  lottery: Lottery
  datasetKind: DatasetKind
}
export interface Drawing {
  id: string
  issue: string
  draw_date: string
  main_numbers: number[]
  special_numbers: number[]
  source: string
  dataset_kind: DatasetKind
  sales: string | null
  pool_amount: string | null
  prizes: Record<string, string>
}
export interface Frequency {
  number: number
  count: number
  frequency: number
  expected_frequency: number
  omission: number
  confidence_interval: number[]
}
export interface Statistics {
  family: 'pool' | 'digit'
  sample_size: number
  frequency: { main: Frequency[]; special: Frequency[] }
  trajectory: {
    issue: string
    date: string
    sum: number
    span: number
    odd: number
    repeated: number | null
  }[]
  expected_sum: number
  mean_sum: number | null
  sum_distribution: { sum: number; observed: number; expected: number; probability: number }[]
  odd_distribution: { odd: number; observed: number; expected: number }[]
  overlap_pmf: number[]
  regions: { label: string; count: number; mean_per_draw: number; expected_per_draw: number }[]
  cooccurrence: { numbers: number[]; count: number; frequency: number; expected_count: number }[]
  structure: {
    mean_span: number | null
    mean_odd: number | null
    mean_high: number | null
    mean_consecutive_pairs: number | null
    mean_repeated: number | null
    repeat_comparisons: number
    high_from: number
  }
}
export interface Rule {
  code: Lottery
  name: string
  main_max: number
  main_count: number
  special_max: number
  special_count: number
  combinations: number
}
export interface Overview {
  total: number
  first_date: string | null
  last_date: string | null
  latest: Drawing | null
  sources: string[]
  quality_issues: number
  experiments: number
  rule: Rule
  statistics: Statistics
}
export interface Health {
  status: string
  database: string
  can_write: boolean
  can_read: boolean
  worker_ready: boolean
  execution_mode: 'worker' | 'request'
  job_timeout_seconds: number
  max_csv_bytes: number
}
export interface Job<T = unknown> {
  id: string
  kind: string
  lottery: Lottery
  dataset_kind: DatasetKind
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  created_at: string
  finished_at: string | null
  error: string | null
  dataset_id: string | null
  params: Record<string, unknown>
  result?: T | null
}
export interface IngestionResult {
  accepted: number
  received: number
  duplicates: number
  rejected: number
  conflicts: number
  warnings?: string[]
}
export interface IngestionRun extends Omit<IngestionResult, 'warnings'> {
  id: string
  source: string
  source_url: string
  snapshot_hash: string
  created_at: string
  warnings: number
}
export interface Quality {
  id: string
  issue: string | null
  row: number
  severity: string
  reason: string
  created_at: string
  resolution_state: string
  existing_identity_hash: string | null
  existing_record_hash: string | null
  existing: Drawing | null
  incoming: Pick<
    Drawing,
    'draw_date' | 'main_numbers' | 'special_numbers' | 'sales' | 'pool_amount' | 'prizes'
  > | null
}
export interface RandomnessResult {
  sample_size: number
  trials: number
  seed: number
  number_of_tests: number
  significant_count: number
  verdict: string
  interpretation: string
  limitations: string[]
  tests: {
    name: string
    method: string
    statistic: number
    p_value: number
    adjusted_p_value: number
    significant: boolean
    effect_size: number
    effect_label: string
  }[]
}
export interface ModelResult {
  model: string
  name: string
  verdict: string
  cost: string
  gross: string | null
  roi: number | null
  metrics: Record<string, number>
  calibration: { predicted: number; observed: number; count: number }[]
  comparison: {
    delta: number
    confidence_interval: number[]
    p_value: number
    adjusted_p_value: number
    effect_size: number
  } | null
  stability: {
    verdict: string
    first_half: number | null
    second_half: number | null
    n: number
  } | null
}
export interface PredictionRow {
  issue: string
  date: string
  main_hits: number
  special_hits: number
  main_brier: number
  main_ticket: number[]
  special_ticket: number[]
}
export interface BacktestResult {
  sample_size: number
  start_issue: string
  end_issue: string
  train_first_issue: string
  models: ModelResult[]
  records: Record<string, PredictionRow[]>
  fit_events: unknown[]
  code_fingerprint: string
  feature_version: string
  primary_metric: string
  comparison_method: string
  stability_method: string
  limitations: string[]
}
export interface SimulationResult {
  iterations: number
  seed: number
  mean_hits: number
  expected_hits: number
  mean_confidence_interval: number[]
  jackpots: number
  jackpot_probability: number
  jackpot_confidence_interval: number[]
  note: string
  distribution: {
    hits: number
    count: number
    observed: number
    theoretical: number
    confidence_interval: number[]
  }[]
}
export interface Ticket {
  main_numbers: number[]
  special_numbers: number[]
}
export interface CoverResult {
  tickets: Ticket[]
  cost: string
  tuple_coverage: number
  covered_tuples: number
  total_tuples: number
  conditional_main_coverage: number
  conditional_draws_total: number
  unconditional_main_coverage: number
  unconditional_confidence_interval: number[]
  duplicate_tuple_fraction: number
  condition: string
  limitations: string
  gains: { tickets: number; covered_tuples: number; new_tuples: number }[]
}

let adminToken = ''
export function setAdminToken(token: string) {
  adminToken = token
}
export function query(scope: Scope, extra: Record<string, string | number> = {}) {
  return new URLSearchParams({
    lottery: scope.lottery,
    dataset_kind: scope.datasetKind,
    ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, String(v)])),
  }).toString()
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (adminToken) headers.set('X-Admin-Token', adminToken)
  const response = await fetch(`/api/v1${path}`, { ...init, headers })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const error = await response.json()
      if (typeof error.detail === 'string') message = error.detail
      else if (Array.isArray(error.detail))
        message = error.detail.map((e: { msg: string }) => e.msg).join('；')
    } catch {
      /* A disconnected proxy may return plain text. */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
export function useResource<T>(path: string, version = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const reload = useCallback(() => setRefresh((n) => n + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setData(value)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '无法读取数据')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [path, version, refresh])
  return { data, error, loading, reload }
}
export function useJob<T>(id: string | null) {
  const [job, setJob] = useState<Job<T> | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setJob(null)
    setError('')
    if (!id) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let failures = 0
    async function poll() {
      try {
        const value = await api<Job<T>>(`/jobs/${id}`, { signal: controller.signal })
        if (controller.signal.aborted) return
        failures = 0
        setError('')
        setJob(value)
        if (value.status === 'queued' || value.status === 'running') timer = setTimeout(poll, 1200)
      } catch (e) {
        if (controller.signal.aborted) return
        failures += 1
        if (failures < 5) {
          timer = setTimeout(poll, 2000 * failures)
        } else {
          setError(e instanceof Error ? e.message : '任务读取失败')
        }
      }
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [id])
  return { job, error }
}
export function useExperiment<T>(scope: Scope, kind: string, endpoint: string) {
  const [active, setActive] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const history = useResource<{ items: Job[] }>(`/jobs?${query(scope, { kind })}`)
  const { job, error: jobError } = useJob<T>(active)
  const reloadHistory = history.reload
  useEffect(() => {
    if (job && ['completed', 'failed', 'cancelled'].includes(job.status)) reloadHistory()
  }, [job?.status, job?.id, reloadHistory])
  async function launch(parameters: Record<string, unknown>) {
    setPending(true)
    setError('')
    try {
      const created = await api<Job>(endpoint, {
        method: 'POST',
        body: JSON.stringify({ lottery: scope.lottery, dataset_kind: scope.datasetKind, ...parameters }),
      })
      setActive(created.id)
      reloadHistory()
    } catch (e) {
      setError(e instanceof Error ? e.message : '无法创建任务')
      reloadHistory()
    } finally {
      setPending(false)
    }
  }
  return { job, active, setActive, pending, error: error || jobError, history, launch }
}
export const fmt = (n: number | null | undefined, digits = 0) =>
  n == null || !Number.isFinite(n) ? '—' : n.toLocaleString('zh-CN', { maximumFractionDigits: digits })
export const pct = (n: number | null | undefined, digits = 1) =>
  n == null ? '—' : `${fmt(n * 100, digits)}%`
export const stamp = (s: string) =>
  new Date(s.endsWith('Z') || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`).toLocaleString('zh-CN', {
    hour12: false,
  })
