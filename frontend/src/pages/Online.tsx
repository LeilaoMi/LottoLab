import { useState } from 'react'
import { useResource } from '../api'
import { ErrorNote, Loading } from '../components'
import { useWorkspace } from '../Workspace'

interface RecommendResult {
  kind: string
  main: string[]
  aux: string[]
}

export function OnlinePage() {
  const { lottery, datasetKind, version } = useWorkspace()
  const [seed, setSeed] = useState(1)
  const rec = useResource<RecommendResult>(`/recommend?kind=${lottery}&seed=${seed}`, version)
  const data = rec.data

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>在线工具</h1>
          <p className="muted">统一后端提供：推荐、注数计算、验奖。随机游戏，仅供分析娱乐。</p>
        </div>
      </header>

      {datasetKind !== 'real' && (
        <div className="notice">在线工具读取真实开奖，请切到“真实数据”。</div>
      )}

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

        <ErrorNote message={rec.error} />
        {rec.loading && !data && <Loading />}

        {data && (
          <div className="grid">
            <div>
              <p className="muted">主区</p>
              <p className="numbers">{data.main.join('  ')}</p>
            </div>
            {data.aux.length > 0 && (
              <div>
                <p className="muted">辅区</p>
                <p className="numbers">{data.aux.join('  ')}</p>
              </div>
            )}
          </div>
        )}

        {!rec.loading && !data && !rec.error && (
          <p>该彩种暂无可用开奖数据（小彩种待接入统一库）。</p>
        )}
      </article>
    </section>
  )
}
