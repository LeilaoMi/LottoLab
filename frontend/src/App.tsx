import {
  BarChart3,
  BookOpen,
  Database,
  Dices,
  FlaskConical,
  Grid3X3,
  LayoutDashboard,
  Menu,
  Moon,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sun,
  Upload,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, setAdminToken, useJob, useResource } from './api'
import type { DatasetKind, Health, IngestionResult, Job, Lottery } from './api'
import { Empty, ErrorNote, JobStatus, Loading } from './components'
import { Workspace } from './Workspace'
import { Dashboard } from './pages/Dashboard'
import { Draws } from './pages/Draws'
import { StatisticsPage } from './pages/Statistics'
import { ModelsPage, BacktestPage } from './pages/Backtest'
import { SimulationPage, CoverPage, MethodologyPage } from './pages/Experiments'
import { OnlinePage } from './pages/Online'

const navigation = [
  ['overview', '开奖观察', LayoutDashboard],
  ['online', '在线工具', Sparkles],
  ['draws', '开奖数据', Database],
  ['statistics', '统计检验', BarChart3],
  ['models', '模型档案', Grid3X3],
  ['backtest', '滚动回测', FlaskConical],
  ['simulation', '随机模拟', Dices],
  ['covering', '组合覆盖', Grid3X3],
  ['methodology', '研究方法', BookOpen],
] as const

export function App() {
  const [route, setRoute] = useState(window.location.hash.slice(2) || 'overview')
  const [lottery, setLottery] = useState<Lottery>(() =>
    localStorage.getItem('lottolab-lottery') === 'dlt' ? 'dlt' : 'ssq',
  )
  const [datasetKind, setDatasetKind] = useState<DatasetKind>('real')
  const [version, setVersion] = useState(0)
  const [mobile, setMobile] = useState(false)
  const [dark, setDark] = useState(localStorage.getItem('lottolab-theme') === 'dark')
  const [importOpen, setImportOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [sourcePending, setSourcePending] = useState(false)
  const refresh = useCallback(() => setVersion((value) => value + 1), [])
  const health = useResource<Health>('/health', version)
  const { job, error: jobError } = useJob<IngestionResult>(activeJob)
  useEffect(() => {
    const handle = () => {
      setRoute(window.location.hash.slice(2) || 'overview')
      setMobile(false)
    }
    window.addEventListener('hashchange', handle)
    return () => window.removeEventListener('hashchange', handle)
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('lottolab-theme', dark ? 'dark' : 'light')
  }, [dark])
  useEffect(() => {
    localStorage.setItem('lottolab-lottery', lottery)
  }, [lottery])
  const reloadHealth = health.reload
  useEffect(() => {
    // Idle cloud tabs must allow the free database to suspend.
    if (health.data?.execution_mode !== 'worker') return
    const timer = setInterval(reloadHealth, 15000)
    return () => clearInterval(timer)
  }, [reloadHealth, health.data?.execution_mode])
  useEffect(() => {
    if (health.data?.can_read === false) setAuthOpen(true)
  }, [health.data?.can_read])
  useEffect(() => {
    if (job?.status === 'completed') refresh()
  }, [job?.status, job?.id, refresh])
  async function launchSource(demo = false) {
    if (sourcePending) return
    setSourcePending(true)
    setActionError('')
    setDatasetKind(demo ? 'synthetic' : 'real')
    try {
      const created = await api<Job>(demo ? '/datasets/demo' : '/sources/sync', {
        method: 'POST',
        body: JSON.stringify({
          lottery,
          dataset_kind: demo ? 'synthetic' : 'real',
          count: demo ? 600 : 1000,
        }),
      })
      setActiveJob(created.id)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '任务创建失败')
    } finally {
      setSourcePending(false)
    }
  }
  const pages: Record<string, React.ComponentType> = {
    overview: Dashboard,
    online: OnlinePage,
    draws: Draws,
    statistics: StatisticsPage,
    models: ModelsPage,
    backtest: BacktestPage,
    simulation: SimulationPage,
    covering: CoverPage,
    methodology: MethodologyPage,
  }
  const CurrentPage = pages[route] || Dashboard
  const busy = sourcePending || job?.status === 'queued' || job?.status === 'running'
  const readable = health.data?.can_read === true
  return (
    <Workspace.Provider
      value={{
        lottery,
        datasetKind,
        version,
        health: health.data,
        refresh,
        setLottery,
        setDatasetKind,
        openImport: () => setImportOpen(true),
        sync: () => void launchSource(),
        demo: () => void launchSource(true),
      }}
    >
      <div className="app-shell">
        {mobile && (
          <button className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMobile(false)} />
        )}
        <aside className={`sidebar ${mobile ? 'sidebar-open' : ''}`}>
          <a className="brand" href="#/overview">
            <span className="brand-mark">
              <i />
              <i />
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
            <span>
              LottoLab<small>数据与概率实验室</small>
            </span>
          </a>
          <div className="sidebar-caption">研究工作台</div>
          <nav aria-label="主导航">
            {navigation.map(([id, label, Icon]) => (
              <a
                key={id}
                href={`#/${id}`}
                className={route === id ? 'active' : ''}
                aria-current={route === id ? 'page' : undefined}
              >
                <Icon size={19} strokeWidth={1.7} />
                {label}
              </a>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="system-status">
              <span className={`live-dot ${health.data ? '' : 'offline'}`} />
              <span>
                {health.data ? '数据服务已连接' : '正在连接数据服务'}
                <small>
                  {health.data?.execution_mode === 'request'
                    ? '云端按需计算'
                    : health.data?.worker_ready
                      ? '计算服务在线'
                      : '计算服务待就绪'}
                </small>
              </span>
            </div>
            <button className="theme-switch" onClick={() => setDark(!dark)}>
              {dark ? <Sun size={17} /> : <Moon size={17} />}
              {dark ? '切换浅色' : '切换深色'}
            </button>
            <p>
              观察随机，验证假设。
              <br />
              每一个结论，都保留证据。
            </p>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <div className="topbar-left">
              <button
                className="icon-button menu-toggle"
                aria-label="打开导航"
                onClick={() => setMobile(!mobile)}
              >
                <Menu size={22} />
              </button>
              <label className="lottery-select">
                <select
                  aria-label="选择彩种"
                  value={lottery}
                  onChange={(e) => setLottery(e.target.value as Lottery)}
                >
                  <option value="ssq">双色球</option>
                  <option value="dlt">大乐透</option>
                </select>
              </label>
              <div className="dataset-switch" aria-label="数据类型">
                <button
                  aria-pressed={datasetKind === 'real'}
                  className={datasetKind === 'real' ? 'active' : ''}
                  onClick={() => setDatasetKind('real')}
                >
                  真实数据
                </button>
                <button
                  aria-pressed={datasetKind === 'synthetic'}
                  className={datasetKind === 'synthetic' ? 'active' : ''}
                  onClick={() => setDatasetKind('synthetic')}
                >
                  演示数据
                </button>
              </div>
            </div>
            <div className="topbar-actions">
              <button
                className="icon-button"
                aria-label="管理权限"
                title="管理权限"
                onClick={() => setAuthOpen(true)}
              >
                <ShieldCheck size={19} />
              </button>
              <button
                className="button sync-button"
                onClick={() => void launchSource()}
                disabled={busy || !readable}
              >
                <RefreshCw size={16} className={busy ? 'spin' : ''} />
                <span>同步数据</span>
              </button>
              <button
                className="button button-primary import-button"
                onClick={() => setImportOpen(true)}
                disabled={!readable}
              >
                <Upload size={16} />
                <span>导入 CSV</span>
              </button>
            </div>
          </header>
          <main className="main-content">
            {datasetKind === 'synthetic' && (
              <div className="notice notice-demo">当前查看演示/测试数据，仅用于验证功能与方法。</div>
            )}
            <ErrorNote message={health.error || actionError || jobError} />
            {sourcePending && (
              <div className="notice" role="status">
                正在同步并校验数据，请保持页面打开。完成后会保存导入记录。
              </div>
            )}
            {activeJob && (
              <div className="global-job">
                <JobStatus job={job} />
                {job?.status === 'completed' && job.result && (
                  <div className="import-summary">
                    新增 {job.result.accepted} 期，重复 {job.result.duplicates} 期，隔离{' '}
                    {job.result.rejected + job.result.conflicts} 条。
                    <button className="text-button" onClick={() => setActiveJob(null)}>
                      收起
                    </button>
                  </div>
                )}
              </div>
            )}
            {readable ? (
              <>
                {health.data?.execution_mode === 'request' && (
                  <div className="notice">
                    云端每次运行一项实验，单次最多 {health.data.job_timeout_seconds} 秒。
                    提交后请等待完成；连接中断时可从实验历史查看状态。
                  </div>
                )}
                <CurrentPage key={`${route}-${lottery}-${datasetKind}`} />
              </>
            ) : health.data ? (
              <Empty title="进入私人工作台">
                验证管理员令牌后，即可查看数据和运行实验。
                <button className="button button-primary" onClick={() => setAuthOpen(true)}>
                  验证访问权限
                </button>
              </Empty>
            ) : health.loading ? (
              <Loading />
            ) : null}
          </main>
          <footer className="footer">
            <span>LottoLab</span>
            <p>用于历史数据分析、统计实验与概率教育，不提供中奖保证，也不构成购彩建议。</p>
            <a href="#/methodology">方法与边界</a>
          </footer>
        </div>
      </div>
      {importOpen && (
        <ImportDialog
          lottery={lottery}
          kind={datasetKind}
          onClose={() => setImportOpen(false)}
          onSuccess={refresh}
          maxBytes={health.data?.max_csv_bytes ?? 8 * 1024 * 1024}
        />
      )}
      {authOpen && <AuthDialog onClose={() => setAuthOpen(false)} onSuccess={refresh} />}
    </Workspace.Provider>
  )
}

function ImportDialog({
  lottery,
  kind,
  onClose,
  onSuccess,
  maxBytes,
}: {
  lottery: Lottery
  kind: DatasetKind
  onClose: () => void
  onSuccess: () => void
  maxBytes: number
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState<IngestionResult | null>(null)
  useEffect(() => {
    dialog.current?.showModal()
  }, [])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    if (file.size > maxBytes) {
      setError(`文件不能超过 ${maxBytes / (1024 * 1024)} MB`)
      return
    }
    setPending(true)
    setError('')
    const data = new FormData()
    data.set('file', file)
    data.set('lottery', lottery)
    data.set('dataset_kind', kind)
    try {
      setResult(await api<IngestionResult>('/imports/csv', { method: 'POST', body: data }))
      onSuccess()
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败')
    } finally {
      setPending(false)
    }
  }
  return (
    <dialog ref={dialog} className="dialog" onCancel={onClose} aria-labelledby="import-title">
      <button className="dialog-close icon-button" onClick={onClose} aria-label="关闭导入窗口">
        <X size={21} />
      </button>
      <h2 id="import-title">导入开奖记录</h2>
      <p>
        导入到{lottery === 'ssq' ? '双色球' : '大乐透'} · {kind === 'real' ? '真实数据' : '演示数据'}
        。每条记录会先校验，冲突不会覆盖原数据。
      </p>
      <form onSubmit={submit}>
        <label className="file-picker">
          <Upload size={28} />
          <strong>{file?.name || '选择 CSV 文件'}</strong>
          <span>支持 UTF-8 / GB18030，最多 {maxBytes / (1024 * 1024)} MB</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            required
          />
        </label>
        <div className="csv-guide">
          <strong>必要列</strong>
          <code>issue,draw_date,main_numbers,special_numbers</code>
          <p>号码之间使用空格；真实期号如 2026105，日期如 2026-09-10。</p>
        </div>
        <ErrorNote message={error} />
        {result && (
          <div className="notice notice-success">
            新增 {result.accepted} 条，重复 {result.duplicates} 条，隔离 {result.rejected + result.conflicts}{' '}
            条。详细原因可在“质量报告”中查看。
          </div>
        )}
        <div className="dialog-actions">
          <button type="button" className="button" onClick={onClose}>
            {result ? '完成' : '取消'}
          </button>
          <button className="button button-primary" disabled={!file || pending}>
            {pending ? '正在校验并导入' : '校验并导入'}
          </button>
        </div>
      </form>
    </dialog>
  )
}

function AuthDialog({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    dialog.current?.showModal()
  }, [])
  async function submit(event: FormEvent) {
    event.preventDefault()
    setAdminToken(token)
    try {
      const status = await api<Health>('/health')
      if (!status.can_write) throw new Error('令牌无效或当前来源未获授权')
      onSuccess()
      onClose()
    } catch (e) {
      setAdminToken('')
      setError(e instanceof Error ? e.message : '无法验证权限')
    }
  }
  return (
    <dialog ref={dialog} className="dialog" onCancel={onClose} aria-labelledby="auth-title">
      <button className="dialog-close icon-button" onClick={onClose} aria-label="关闭权限窗口">
        <X size={20} />
      </button>
      <h2 id="auth-title">管理权限</h2>
      <p>
        私人云端工作台需要管理员令牌才能访问。令牌仅保存在当前页面内存中，刷新页面后需重新验证。本地访问由启动配置决定。
      </p>
      <form onSubmit={submit}>
        <label>
          管理员令牌
          <input
            autoComplete="off"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
        </label>
        <ErrorNote message={error} />
        <div className="dialog-actions">
          <button type="button" className="button" onClick={onClose}>
            取消
          </button>
          <button className="button button-primary">验证权限</button>
        </div>
      </form>
    </dialog>
  )
}
