import { AlertCircle, CheckCircle2, Clock3, Loader2, Play, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { api, fmt, stamp } from './api'
import type { Job, Ticket } from './api'

export function Balls({
  main,
  special,
  compact = false,
}: {
  main: number[]
  special: number[]
  compact?: boolean
}) {
  return (
    <div
      className={`balls ${compact ? 'balls-compact' : ''}`}
      aria-label={
        special.length > 0
          ? `主区 ${main.join('、')}，附加区 ${special.join('、')}`
          : `主区 ${main.join('、')}`
      }
    >
      {main.map((n) => (
        <span className="ball ball-main" key={`m${n}`}>
          {String(n).padStart(2, '0')}
        </span>
      ))}
      {special.length > 0 && (
        <>
          <span className="ball-divider" />
          {special.map((n) => (
            <span className="ball ball-special" key={`s${n}`}>
              {String(n).padStart(2, '0')}
            </span>
          ))}
        </>
      )}
    </div>
  )
}
export function ErrorNote({ message }: { message?: string | null }) {
  return message ? (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  ) : null
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <Loader2 size={22} className="spin" />
      正在读取数据
    </div>
  )
}
export function Empty({ title = '这里还没有数据', children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-dots">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <h3>{title}</h3>
      <p>{children || '同步公开数据或导入 CSV，即可开始分析。'}</p>
    </div>
  )
}
export function PageTitle({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = '',
}: {
  title?: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-heading">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}
export function Metric({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}
const jobNames: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
export function JobStatus({ job }: { job: Job | null }) {
  const [cancelError, setCancelError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  useEffect(() => {
    setCancelError('')
    setCancelling(false)
  }, [job?.id])
  if (!job) return null
  const jobId = job.id
  async function cancel() {
    setCancelling(true)
    setCancelError('')
    try {
      await api(`/jobs/${jobId}/cancel`, { method: 'POST' })
    } catch (error) {
      setCancelError(error instanceof Error ? error.message : '取消失败，请重试')
    } finally {
      setCancelling(false)
    }
  }
  const working = job.status === 'queued' || job.status === 'running'
  return (
    <div className={`job-status job-${job.status}`} role="status">
      {working ? (
        <Loader2 size={20} className="spin" />
      ) : job.status === 'completed' ? (
        <CheckCircle2 size={20} />
      ) : (
        <AlertCircle size={20} />
      )}
      <div className="grow">
        <strong>{jobNames[job.status]}</strong>
        <p>
          {job.error ||
            (working
              ? '计算在后台继续，你可以浏览其他页面。'
              : `任务 ${job.id.slice(0, 8)} · ${stamp(job.created_at)}`)}
        </p>
        {working && <progress max={100} value={job.progress} aria-label="任务进度" />}
        <ErrorNote message={cancelError} />
      </div>
      {working && (
        <button className="button button-quiet" disabled={cancelling} onClick={() => void cancel()}>
          <X size={15} />
          {cancelling ? '正在取消' : '取消'}
        </button>
      )}
    </div>
  )
}
export function History({
  items,
  active,
  onSelect,
}: {
  items: Job[]
  active: string | null
  onSelect: (id: string) => void
}) {
  return (
    <Panel title="实验记录" subtitle="每次运行独立保存，便于回看与复核。">
      {!items.length ? (
        <div className="subtle-empty">运行第一次实验后，结果会保留在这里。</div>
      ) : (
        <div className="history-list">
          {items.slice(0, 8).map((job) => (
            <button
              key={job.id}
              className={`history-item ${active === job.id ? 'active' : ''}`}
              onClick={() => onSelect(job.id)}
            >
              <Clock3 size={17} />
              <span>
                {stamp(job.created_at)}
                <small>
                  {job.id.slice(0, 8)}
                  {job.dataset_id ? ` · 数据 ${job.dataset_id.slice(0, 8)}` : ' · 理论模拟'}
                </small>
              </span>
              <span className={`badge badge-${job.status}`}>{jobNames[job.status]}</span>
            </button>
          ))}
        </div>
      )}
    </Panel>
  )
}
export function RunButton({
  disabled,
  pending,
  label = '运行实验',
}: {
  disabled?: boolean
  pending?: boolean
  label?: string
}) {
  return (
    <button className="button button-primary" disabled={disabled || pending} type="submit">
      {pending ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
      {pending ? '正在处理，请稍候' : label}
    </button>
  )
}
export function Tickets({ tickets }: { tickets: Ticket[] }) {
  return (
    <div className="ticket-list">
      {tickets.map((ticket, index) => (
        <div className="ticket-row" key={`${ticket.main_numbers.join(',')}-${index}`}>
          <span className="ticket-index">第 {fmt(index + 1)} 注</span>
          <Balls main={ticket.main_numbers} special={ticket.special_numbers} compact />
        </div>
      ))}
    </div>
  )
}
export function Verdict({ value }: { value: string }) {
  const labels: Record<string, string> = {
    BASELINE: '参照基线',
    NOT_SIGNIFICANT: '未检出显著优势',
    SIGNIFICANT: '存在待复核优势',
    WORSE_THAN_BASELINE: '弱于基线',
    WEAK_SIGNAL: '证据较弱',
    REVIEW_NEEDED: '需要复核',
  }
  return (
    <span
      className={`badge ${value === 'SIGNIFICANT' || value === 'REVIEW_NEEDED' ? 'badge-review' : value === 'WORSE_THAN_BASELINE' ? 'badge-failed' : 'badge-neutral'}`}
    >
      {labels[value] || value}
    </span>
  )
}
