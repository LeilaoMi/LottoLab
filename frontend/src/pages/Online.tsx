import { useState } from 'react'
import { api, useResource } from '../api'
import { ErrorNote, Loading } from '../components'
import { useWorkspace } from '../Workspace'

interface RecommendResult {
  kind: string
  main: string[]
  aux: string[]
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

export function OnlinePage() {
  const { lottery, datasetKind, version } = useWorkspace()
  const [seed, setSeed] = useState(1)
  const recommend = useResource<RecommendResult>(`/recommend?kind=${lottery}&seed=${seed}`, version)

  const [mainCount, setMainCount] = useState(lottery === 'ssq' ? 7 : 6)
  const [auxCount, setAuxCount] = useState(lottery === 'ssq' ? 1 : 3)
  const [bet, setBet] = useState<BetResult | null>(null)
  const [betErr, setBetErr] = useState('')

  const [tickets, setTickets] = useState('')
  const [codes, setCodes] = useState('')
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [verifyErr, setVerifyErr] = useState('')

  async function calcBet() {
    setBetErr('')
    const params =
      lottery === 'ssq' ? { red: mainCount, blue: auxCount } : { front: mainCount, back: auxCount }
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
      setVerify(
        await api<VerifyResult>('/verify', {
          method: 'POST',
          body: JSON.stringify({ kind: lottery, lines, codes: codeList }),
        }),
      )
    } catch (e) {
      setVerifyErr(e instanceof Error ? e.message : '验奖失败')
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
          </div>
        </div>
        <ErrorNote message={recommend.error} />
        {recommend.loading && !recommend.data && <Loading />}
        {recommend.data && (
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
        )}
        {!recommend.loading && !recommend.data && !recommend.error && (
          <p>该彩种暂无可用开奖数据（小彩种待接入统一库）。</p>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>注数与金额</h2>
        </div>
        <div className="inline-actions">
          <label className="muted">
            主区号码数
            <input
              type="number"
              min={5}
              max={33}
              value={mainCount}
              onChange={(e) => setMainCount(+e.target.value)}
            />
          </label>
          <label className="muted">
            辅区号码数
            <input
              type="number"
              min={1}
              max={16}
              value={auxCount}
              onChange={(e) => setAuxCount(+e.target.value)}
            />
          </label>
          <button className="button button-primary" onClick={() => void calcBet()}>
            计算
          </button>
        </div>
        <ErrorNote message={betErr} />
        {bet && (
          <p>
            {bet.formula} → <strong>{bet.bets}</strong> 注 · <strong>¥{bet.amount}</strong>
            <span className="muted"> （{bet.note}）</span>
          </p>
        )}
      </article>

      <article className="card">
        <div className="card-head">
          <h2>批量验奖</h2>
        </div>
        <label className="muted">
          票面（每行一注，如 01 05 13 14 22 30 + 04）
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
