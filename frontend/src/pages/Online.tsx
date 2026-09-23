import { useState } from 'react'
import { api, useResource } from '../api'
import type { Lottery } from '../api'
import { ErrorNote, Loading } from '../components'
import { useWorkspace } from '../Workspace'

interface ColdFactor {
  key: string
  label: string
  effect: number
}
interface Coldness {
  supported: boolean
  ratio?: number
  label?: string
  estWinners?: number
  avgFirstWinners?: number
  factors?: ColdFactor[]
  note?: string
}
interface RecommendPick {
  name: string
  main: string[]
  aux: string[]
  score: number | null
  collision: number
  coldness?: Coldness
}
interface RecommendResult {
  kind: string
  main: string[]
  aux: string[]
  family: 'pool' | 'digit'
  picks: RecommendPick[]
  analysis: {
    window?: number
    hot?: string[]
    cold?: string[]
    avg_sum?: number | null
    avg_ac?: number | null
    road012?: number[]
    prime_share?: number | null
  }
  disclaimer?: string
}
interface BetResult {
  kind: string
  mode: string
  formula: string
  bets: number
  amount: number
  note: string
}
interface VerifyRow {
  ticket: string
  grade?: string
  amount?: number | null
  error?: string
}
interface VerifyRound {
  code: string
  drawn: boolean
  results: VerifyRow[]
}
interface VerifyResult {
  kind: string
  rounds: VerifyRound[]
  total: { won: number; amount: number; amount_unknown: number }
}
interface ReviewRow {
  id: string
  kind: string
  target_issue: string
  strategy: string
  checked: boolean
  hit_main: number | null
  prize: string | null
}
interface ReviewSummary {
  kind: string
  logged: number
  checked: number
  avg_hit_main: number | null
  expected_hit: number
  won_count: number
  note: string
  rows: ReviewRow[]
}
interface BacktestStrategy {
  name: string
  mean_hits: number
  hit_distribution: Record<string, number>
}
interface BacktestResult {
  kind: string
  family: string
  tested: number
  expected_mean_hits: number
  strategies: BacktestStrategy[]
  disclaimer: string
}

function downloadPicksCsv(kind: string, picks: RecommendPick[]) {
  const header = '彩种,策略,主区,辅区,结构分,撞号指数'
  const rows = picks.map((p) =>
    [kind, p.name, p.main.join(' '), p.aux.join(' '), p.score ?? '', p.collision].join(','),
  )
  const csv = '' + [header, ...rows].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${kind}-推荐票面.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function OnlinePage() {
  const { lottery, datasetKind, version } = useWorkspace()
  const [seed, setSeed] = useState(1)
  const recommend = useResource<RecommendResult>(`/recommend?kind=${lottery}&seed=${seed}`, version)

  const DIGIT_KINDS: Lottery[] = ['fc3d', 'pl3', 'pl5', 'qxc']
  const digitNeed = lottery === 'pl5' ? 5 : lottery === 'qxc' ? 7 : 3
  const isDigit = DIGIT_KINDS.includes(lottery)
  const [pos, setPos] = useState<number[]>(Array.from({ length: digitNeed }, () => 1))
  const [klPick, setKlPick] = useState(10)
  const [mainCount, setMainCount] = useState(lottery === 'ssq' ? 7 : lottery === 'qlc' ? 7 : 6)
  const [auxCount, setAuxCount] = useState(lottery === 'ssq' ? 1 : lottery === 'qlc' ? 1 : 3)
  const [betMode, setBetMode] = useState<'duplex' | 'dantuo'>('duplex')
  const [danCount, setDanCount] = useState(2)
  const [bet, setBet] = useState<BetResult | null>(null)
  const [betErr, setBetErr] = useState('')

  const [tickets, setTickets] = useState('')
  const [codes, setCodes] = useState('')
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [verifyErr, setVerifyErr] = useState('')

  const [bt, setBt] = useState<BacktestResult | null>(null)
  const [btErr, setBtErr] = useState('')
  const [btLoading, setBtLoading] = useState(false)

  const [predIssue, setPredIssue] = useState('')
  const [review, setReview] = useState<ReviewSummary | null>(null)
  const [predMsg, setPredMsg] = useState('')
  const [predErr, setPredErr] = useState('')
  const [reviewLoading, setReviewLoading] = useState(false)

  async function calcBet() {
    setBetErr('')
    if (isDigit) {
      try {
        setBet(
          await api<BetResult>(
            `/bet?kind=${lottery}&p=${encodeURIComponent(JSON.stringify({ pos: pos.join(',') }))}`,
          ),
        )
      } catch (e) {
        setBetErr(e instanceof Error ? e.message : '计算失败')
      }
      return
    }
    if (lottery === 'kl8') {
      try {
        setBet(
          await api<BetResult>(
            `/bet?kind=kl8&p=${encodeURIComponent(JSON.stringify({ pick: klPick, nums: Math.max(klPick, mainCount) }))}`,
          ),
        )
      } catch (e) {
        setBetErr(e instanceof Error ? e.message : '计算失败')
      }
      return
    }
    let params: Record<string, number>
    if (betMode === 'dantuo') {
      params =
        lottery === 'ssq'
          ? { dan: danCount, tuo: mainCount, blue: auxCount }
          : lottery === 'dlt'
            ? { fdan: danCount, ftuo: mainCount, btuo: auxCount }
            : { dan: danCount, tuo: mainCount }
    } else if (lottery === 'ssq') {
      params = { red: mainCount, blue: auxCount }
    } else if (lottery === 'qlc') {
      params = { main: mainCount }
    } else {
      params = { front: mainCount, back: auxCount }
    }
    try {
      setBet(await api<BetResult>(`/bet?kind=${lottery}&p=${encodeURIComponent(JSON.stringify(params))}`))
    } catch (e) {
      setBetErr(e instanceof Error ? e.message : '计算失败')
    }
  }

  async function runVerify() {
    setVerifyErr('')
    const lines = tickets
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean)
    const codeList = codes
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
    if (!lines.length || !codeList.length) {
      setVerifyErr('请填写票面（每行一注）与期号（逗号分隔）')
      return
    }
    try {
      const query = new URLSearchParams({ kind: lottery })
      query.set('lines', lines.join('\n'))
      query.set('codes', codeList.join(','))
      setVerify(await api<VerifyResult>(`/verify?${query.toString()}`))
    } catch (e) {
      setVerifyErr(e instanceof Error ? e.message : '验奖失败')
    }
  }

  async function runBacktest() {
    setBtErr('')
    setBtLoading(true)
    try {
      setBt(await api<BacktestResult>(`/recommend/backtest?kind=${lottery}`))
    } catch (e) {
      setBtErr(e instanceof Error ? e.message : '回测失败')
    } finally {
      setBtLoading(false)
    }
  }

  async function logPrediction() {
    setPredErr('')
    setPredMsg('')
    const picks = (recommend.data?.picks || []).map((p) => ({ strategy: p.name, main: p.main, aux: p.aux }))
    if (!predIssue.trim() || !picks.length) {
      setPredErr('请填写目标期号，且当前有可记录的推荐')
      return
    }
    try {
      const r = await api<{ logged: number }>('/predictions', {
        method: 'POST',
        body: JSON.stringify({ kind: lottery, target_issue: predIssue.trim(), seed, picks }),
      })
      setPredMsg(`已记录 ${r.logged} 注到台账，等待 ${predIssue} 期开奖后自动对账`)
    } catch (e) {
      setPredErr(e instanceof Error ? e.message : '记录失败')
    }
  }

  async function loadReview() {
    setPredErr('')
    setReviewLoading(true)
    try {
      setReview(await api<ReviewSummary>(`/predictions/review?kind=${lottery}&reconcile=true`))
    } catch (e) {
      setPredErr(e instanceof Error ? e.message : '复盘加载失败')
    } finally {
      setReviewLoading(false)
    }
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>在线工具</h1>
          <p className="muted">统一后端提供：推荐、注数计算、验奖。随机游戏，仅供分析娱乐。</p>
        </div>
      </header>

      {datasetKind !== 'real' && <div className="notice">在线工具读取真实开奖，请切到“真实数据”。</div>}

      <article className="card">
        <div className="card-head">
          <h2>号码推荐</h2>
          <div className="inline-actions">
            <span className="muted">seed</span>
            <button className="button" onClick={() => setSeed((s) => Math.max(1, s - 1))}>
              −
            </button>
            <span>{seed}</span>
            <button className="button" onClick={() => setSeed((s) => s + 1)}>
              +
            </button>
            {(recommend.data?.picks?.length ?? 0) > 0 && (
              <button
                className="button button-quiet"
                onClick={() => downloadPicksCsv(lottery, recommend.data!.picks)}
              >
                导出票面 CSV
              </button>
            )}
          </div>
        </div>
        <ErrorNote message={recommend.error} />
        <p className="muted" style={{ marginTop: 0 }}>
          期望提示：每注期望回报为负，推荐只做形态参考；先看下方策略回测，再决定要不要花钱。
        </p>
        {recommend.loading && !recommend.data && <Loading />}
        {recommend.data &&
          (recommend.data.picks && recommend.data.picks.length ? (
            <div>
              {recommend.data.picks.map((p) => (
                <div key={p.name} style={{ padding: '6px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <span className="muted">
                      {p.name}
                      {p.score != null ? ` · 结构分 ${p.score}` : ''}
                      {` · 撞号 ${p.collision}`}
                    </span>
                    <span className="numbers">
                      {p.main.join('  ')}
                      {p.aux.length > 0 ? `  +  ${p.aux.join('  ')}` : ''}
                    </span>
                  </div>
                  {p.coldness &&
                    (p.coldness.supported ? (
                      <p className="muted" style={{ margin: '2px 0 0', fontSize: 12 }}>
                        冷门度 {p.coldness.label} · 预计同奖 {p.coldness.estWinners} 人（平均{' '}
                        {p.coldness.avgFirstWinners}）
                        {p.coldness.factors && p.coldness.factors.length
                          ? ` · 因子：${p.coldness.factors.map((fc) => fc.label).join('；')}`
                          : ''}
                      </p>
                    ) : (
                      <p className="muted" style={{ margin: '2px 0 0', fontSize: 12 }}>
                        {p.coldness.note}
                      </p>
                    ))}
                </div>
              ))}
              {recommend.data.analysis && (recommend.data.analysis.hot?.length ?? 0) > 0 && (
                <p className="muted" style={{ marginTop: 8 }}>
                  近 {recommend.data.analysis.window} 期 · 热号 {recommend.data.analysis.hot?.join(' ')} ·
                  冷号 {recommend.data.analysis.cold?.join(' ')}
                  {recommend.data.analysis.avg_sum != null
                    ? ` · 均和 ${recommend.data.analysis.avg_sum}`
                    : ''}
                  {recommend.data.analysis.avg_ac != null ? ` · 均AC ${recommend.data.analysis.avg_ac}` : ''}
                </p>
              )}
              <p className="muted" style={{ marginTop: 6 }}>
                撞号指数越低，表示这注与大众热选号（生日号、吉利数、整十等）重叠越少；若中头奖需分摊的人越少——不改变中奖概率。
              </p>
              {recommend.data.disclaimer && (
                <p className="muted" style={{ marginTop: 4 }}>
                  {recommend.data.disclaimer}
                </p>
              )}
            </div>
          ) : (
            <div className="grid">
              <div>
                <p className="muted">主区</p>
                <p className="numbers">{recommend.data.main.join('  ')}</p>
              </div>
              {recommend.data.aux.length > 0 && (
                <div>
                  <p className="muted">辅区</p>
                  <p className="numbers">{recommend.data.aux.join('  ')}</p>
                </div>
              )}
            </div>
          ))}
        {!recommend.loading && !recommend.data && !recommend.error && (
          <p>该彩种暂无可用开奖数据（小彩种待接入统一库）。</p>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>策略回测</h2>
          <button className="button" onClick={runBacktest} disabled={btLoading}>
            {btLoading ? '回测中…' : '回测各策略（近 120 期）'}
          </button>
        </div>
        <ErrorNote message={btErr} />
        {bt && (
          <div>
            <p className="muted">
              近 {bt.tested} 期滚动回测 · 均匀模型期望命中 <strong>{bt.expected_mean_hits}</strong>
            </p>
            {bt.strategies.map((s) => (
              <div
                key={s.name}
                style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '5px 0' }}
              >
                <span className="muted">{s.name}</span>
                <span>
                  平均命中 <strong>{s.mean_hits}</strong>
                  <span className="muted">
                    {'  '}
                    {Object.entries(s.hit_distribution)
                      .map(([k, v]) => `${k}中×${v}`)
                      .join(' ')}
                  </span>
                </span>
              </div>
            ))}
            <p className="muted" style={{ marginTop: 6 }}>
              {bt.disclaimer}
            </p>
          </div>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>注数与金额</h2>
        </div>
        {isDigit ? (
          <div className="inline-actions">
            {pos.map((value, index) => (
              <label className="muted" key={index}>
                第 {index + 1} 位
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={value}
                  onChange={(e) => {
                    const next = [...pos]
                    next[index] = Number(e.target.value)
                    setPos(next)
                  }}
                />
              </label>
            ))}
            <button className="button button-primary" onClick={() => void calcBet()}>
              计算
            </button>
          </div>
        ) : lottery === 'kl8' ? (
          <div className="inline-actions">
            <label className="muted">
              选球数
              <input
                type="number"
                min={1}
                max={10}
                value={klPick}
                onChange={(e) => setKlPick(Number(e.target.value))}
              />
            </label>
            <label className="muted">
              投注号码个数
              <input
                type="number"
                min={klPick}
                max={80}
                value={Math.max(klPick, mainCount)}
                onChange={(e) => setMainCount(Number(e.target.value))}
              />
            </label>
            <button className="button button-primary" onClick={() => void calcBet()}>
              计算
            </button>
          </div>
        ) : (
          <>
            {['ssq', 'dlt', 'qlc'].includes(lottery) && (
              <div className="segmented" style={{ marginBottom: 8 }}>
                <button className={betMode === 'duplex' ? 'active' : ''} onClick={() => setBetMode('duplex')}>
                  复式
                </button>
                <button className={betMode === 'dantuo' ? 'active' : ''} onClick={() => setBetMode('dantuo')}>
                  胆拖
                </button>
              </div>
            )}
            <div className="inline-actions">
              {betMode === 'dantuo' && (
                <label className="muted">
                  胆码数
                  <input
                    type="number"
                    min={1}
                    max={lottery === 'dlt' ? 4 : lottery === 'qlc' ? 6 : 5}
                    value={danCount}
                    onChange={(e) => setDanCount(+e.target.value)}
                  />
                </label>
              )}
              <label className="muted">
                {betMode === 'dantuo' ? '拖码数' : '主区号码数'}
                <input
                  type="number"
                  min={betMode === 'duplex' ? (lottery === 'ssq' ? 6 : lottery === 'qlc' ? 7 : 5) : 1}
                  max={lottery === 'ssq' ? 33 : lottery === 'qlc' ? 30 : 35}
                  value={mainCount}
                  onChange={(e) => setMainCount(+e.target.value)}
                />
              </label>
              {lottery !== 'qlc' && (
                <label className="muted">
                  {lottery === 'dlt' && betMode === 'duplex' ? '后区号码数' : '辅区号码数'}
                  <input
                    type="number"
                    min={lottery === 'dlt' && betMode === 'duplex' ? 2 : 1}
                    max={lottery === 'ssq' ? 16 : 12}
                    value={auxCount}
                    onChange={(e) => setAuxCount(+e.target.value)}
                  />
                </label>
              )}
              <button className="button button-primary" onClick={() => void calcBet()}>
                计算
              </button>
            </div>
          </>
        )}
        <ErrorNote message={betErr} />
        {bet && (
          <p>
            {bet.formula} → <strong>{bet.bets}</strong> 注 · <strong>¥{bet.amount}</strong>
            <span className="muted"> （{bet.note}；单期金额，追号/倍投另计）</span>
          </p>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>预测复盘</h2>
        </div>
        <p className="muted">
          把当前推荐登记到台账，等该期开奖后自动对账命中率——用真实结果自证预测准不准（预期≈随机）。
        </p>
        <div className="inline-actions">
          <label className="muted">
            目标期号
            <input
              value={predIssue}
              onChange={(e) => setPredIssue(e.target.value)}
              placeholder="如 2026107"
            />
          </label>
          <button className="button" onClick={() => void logPrediction()}>
            记录当前推荐到台账
          </button>
          <button className="button button-quiet" onClick={() => void loadReview()} disabled={reviewLoading}>
            {reviewLoading ? '加载中…' : '查看复盘对账'}
          </button>
        </div>
        <ErrorNote message={predErr} />
        {predMsg && <p className="muted">{predMsg}</p>}
        {review && (
          <div>
            {review.logged === 0 && (
              <p className="muted" style={{ marginTop: 6 }}>
                暂无台账记录：在上方填写目标期号，把当前推荐记一笔，开奖后再回来对账——空台账说明不了任何事。
              </p>
            )}
            <p className="muted" style={{ marginTop: 6 }}>
              台账 {review.logged} 条 · 已对账 {review.checked} 条 · 平均命中{' '}
              <strong>{review.avg_hit_main ?? '—'}</strong>（随机期望 {review.expected_hit}）· 中奖{' '}
              {review.won_count} 次
            </p>
            <p className="muted" style={{ fontSize: 12 }}>
              {review.note}
            </p>
            {review.rows.slice(0, 12).map((r) => (
              <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}>
                <span className="muted">
                  {r.target_issue} · {r.strategy}
                </span>
                <span>{r.checked ? `中${r.hit_main ?? 0}${r.prize ? ' · ' + r.prize : ''}` : '待开奖'}</span>
              </div>
            ))}
          </div>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>批量验奖</h2>
        </div>
        <label className="muted">
          票面（每行一注；号码空格分隔，有附加区用 + 连接，如 01 05 13 14 22 30 + 04；快乐8/数字型无 +）
          <textarea rows={4} value={tickets} onChange={(e) => setTickets(e.target.value)} />
        </label>
        <label className="muted">
          期号（逗号分隔）
          <input value={codes} onChange={(e) => setCodes(e.target.value)} placeholder="2026105,2026104" />
        </label>
        <button className="button button-primary" onClick={() => void runVerify()}>
          验奖
        </button>
        <ErrorNote message={verifyErr} />
        {verify && (
          <div>
            <p>
              命中 <strong>{verify.total.won}</strong> 注 · 确定金额 <strong>¥{verify.total.amount}</strong>
              {verify.total.amount_unknown > 0 && (
                <span className="muted">
                  {' '}
                  · 另有 {verify.total.amount_unknown} 注为浮动/未定金额（以官方公告为准）
                </span>
              )}
            </p>
            {verify.rounds.map((r) => (
              <div key={r.code} className="verify-round">
                <p className="muted">
                  第 {r.code} 期 {r.drawn ? '' : '（未开奖）'}
                </p>
                {r.results.map((x, i) => (
                  <p key={i}>
                    {x.ticket} → <strong>{x.error ? '格式错误' : x.grade}</strong>
                    {x.error ? `：${x.error}` : x.amount ? ` ¥${x.amount}` : ''}
                  </p>
                ))}
              </div>
            ))}
          </div>
        )}
      </article>
    </section>
  )
}
