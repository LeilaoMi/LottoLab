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
  const path = `/recommend?kind=${lottery}&seed=${seed}`
  const rec = useResource<RecommendResult>(path, version)
  const data = rec.data
  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>在线工具</h1>
          <p className="page-sub">统一后端提供：推荐（频率打分）· 注数计算 · 验奖。随机游戏，仅供分析娱乐。</p>
        </div>
      </header>
      {datasetKind !== 'real' ? (
        <div className="notice">在线工具读取真实开奖，请切到“真实数据”。</div>
      ) : (
        <article className="card">
          <div className="card-head">
            <h2>号码推荐</h2>
            <div className="seed-control">
              <span>seed</span>
              <button className="icon-button" onClick={() => setSeed((s) => Math.max(1, s - 1))}>
                −
              </button>
              <span className="seed-value">{seed}</span>
              <button className="icon-button" onClick={() => setSeed((s) => s + 1)}>
                +
              </button>
            </div>
          </div>
          <ErrorNote message={rec.error} />
          {rec.loading && !data ? (
            <Loading />
          ) : data ? (
            <div className="recommend">
              <div className="zone">
                <span className="zone-label">主区</span>
                {data.main.map((n) => (
                  <span key={n} className="ball">
                    {n}
                  </span>
                ))}
              </div>
              {data.aux.length > 0 && (
                <div className="zone">
                  <span className="zone-label">辅区</span>
                  {data.aux.map((n) => (
                    <span key={n} className="ball ball-special">
                      {n}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p>该彩种暂无可用开奖数据（小彩种将在后续接入统一库）。</p>
          )}
          <p className="disclaimer">推荐仅为历史频率打分，无预测优势；冷热/遗漏类在真实数据上不成立。</p>
        </article>
      )}
    </section>
  )
}
