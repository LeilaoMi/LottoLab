import { useState } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fmt, pct, query, useExperiment, useResource } from '../api'
import type { RandomnessResult, Statistics } from '../api'
import {
  Empty,
  ErrorNote,
  History,
  JobStatus,
  Loading,
  Metric,
  PageTitle,
  Panel,
  RunButton,
  Verdict,
} from '../components'
import { useWorkspace } from '../Workspace'

export function StatisticsPage() {
  const workspace = useWorkspace()
  const [window, setWindow] = useState(300)
  const [area, setArea] = useState<'main' | 'special'>('main')
  const [tab, setTab] = useState<'frequency' | 'structure' | 'tests'>('frequency')
  const [trials, setTrials] = useState(4999)
  const [showAll, setShowAll] = useState(false)
  const [showAllPairs, setShowAllPairs] = useState(false)
  const stats = useResource<Statistics>(
    `/statistics/frequency?${query(workspace, { window })}`,
    workspace.version,
  )
  const experiment = useExperiment<RandomnessResult>(workspace, 'randomness', '/statistics/randomness')
  const result = experiment.job?.status === 'completed' ? experiment.job.result : null
  const data = stats.data
  const isDigit = data?.family === 'digit'
  const pairs = [...(data?.cooccurrence || [])].sort((a, b) => b.count - a.count)
  return (
    <>
      <PageTitle
        title="统计与随机性检验"
        description="区分历史波动与统计证据；所有检验保留假设、方法和校正结果。"
        actions={
          <label className="inline-label">
            观察窗口
            <select aria-label="统计窗口" value={window} onChange={(e) => setWindow(Number(e.target.value))}>
              <option value={30}>最近 30 期</option>
              <option value={100}>最近 100 期</option>
              <option value={300}>最近 300 期</option>
              <option value={1000}>最近 1000 期</option>
            </select>
          </label>
        }
      />
      <div className="tabs" role="tablist" aria-label="统计类型">
        {[
          ['frequency', '频率与遗漏'],
          ...(isDigit ? [] : [['structure', '组合结构']]),
          ['tests', '随机性检验'],
        ].map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'active' : ''}
            onClick={() => setTab(id as typeof tab)}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorNote message={stats.error} />
      {stats.loading ? (
        <Loading />
      ) : !data?.sample_size ? (
        <Empty title="先准备一些历史数据" />
      ) : (
        <>
          {tab === 'frequency' && (
            <Panel
              title="逐号码观察"
              subtitle={`本次窗口实际包含 ${data.sample_size} 期；区间是历史入选频率的 95% Wilson 区间。`}
              action={
                !isDigit && data.frequency.special.length > 0 ? (
                  <div className="segmented">
                    <button className={area === 'main' ? 'active' : ''} onClick={() => setArea('main')}>
                      主区
                    </button>
                    <button className={area === 'special' ? 'active' : ''} onClick={() => setArea('special')}>
                      附加区
                    </button>
                  </div>
                ) : undefined
              }
            >
              <div className="number-map">
                {data.frequency[area].map((item) => (
                  <div key={item.number} className={`number-cell ${area}`}>
                    <span className={`ball ball-${area}`}>{String(item.number).padStart(2, '0')}</span>
                    <strong>
                      {item.count}
                      <small>次</small>
                    </strong>
                    <div className="frequency-track">
                      <i
                        style={{
                          width: `${Math.min(100, (item.frequency / item.expected_frequency) * 55)}%`,
                        }}
                      />
                    </div>
                    <p>遗漏 {item.omission} 期</p>
                  </div>
                ))}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>号码</th>
                      <th>出现次数</th>
                      <th>历史频率</th>
                      <th>理论概率</th>
                      <th>95% 区间</th>
                      <th>当前遗漏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.frequency[area].map((item) => (
                      <tr key={item.number}>
                        <td className="strong">{String(item.number).padStart(2, '0')}</td>
                        <td>{item.count}</td>
                        <td>{pct(item.frequency, 2)}</td>
                        <td>{pct(item.expected_frequency, 2)}</td>
                        <td>
                          {pct(item.confidence_interval[0], 2)} – {pct(item.confidence_interval[1], 2)}
                        </td>
                        <td>{item.omission} 期</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
          {tab === 'structure' && !isDigit && (
            <div className="grid-two">
              <Panel title="主区和值分布" subtitle="理论曲线来自完整组合空间的精确计数。">
                <div className="chart">
                  <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                    <ComposedChart data={data.sum_distribution}>
                      <CartesianGrid strokeDasharray="3 4" vertical={false} />
                      <XAxis dataKey="sum" minTickGap={30} />
                      <YAxis width={32} />
                      <Tooltip />
                      <Legend />
                      <Bar isAnimationActive={false} name="历史次数" dataKey="observed" fill="#84aebe" />
                      <Line
                        isAnimationActive={false}
                        name="理论期望"
                        dataKey="expected"
                        dot={false}
                        stroke="#b85b6c"
                        strokeWidth={2}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
              <Panel title="奇数个数分布" subtitle="按不放回抽样的超几何分布计算理论期望。">
                <div className="chart">
                  <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                    <ComposedChart data={data.odd_distribution}>
                      <CartesianGrid strokeDasharray="3 4" vertical={false} />
                      <XAxis dataKey="odd" />
                      <YAxis width={32} />
                      <Tooltip />
                      <Legend />
                      <Bar
                        isAnimationActive={false}
                        dataKey="observed"
                        name="历史次数"
                        fill="#84aebe"
                        maxBarSize={42}
                      />
                      <Line
                        isAnimationActive={false}
                        dataKey="expected"
                        name="理论期望"
                        stroke="#b85b6c"
                        strokeWidth={2}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
              <Panel
                title="主区形态摘要"
                subtitle={`前四项按 ${data.sample_size} 期计算；重号按窗口内相邻的 ${data.structure.repeat_comparisons} 对已收录开奖计算。`}
              >
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>观察项</th>
                        <th>窗口内均值</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>跨度（最大号 − 最小号）</td>
                        <td>{fmt(data.structure.mean_span, 2)}</td>
                      </tr>
                      <tr>
                        <td>奇数个数</td>
                        <td>{fmt(data.structure.mean_odd, 2)}</td>
                      </tr>
                      <tr>
                        <td>大号个数（≥ {data.structure.high_from}）</td>
                        <td>{fmt(data.structure.mean_high, 2)}</td>
                      </tr>
                      <tr>
                        <td>相邻连号对数</td>
                        <td>{fmt(data.structure.mean_consecutive_pairs, 2)}</td>
                      </tr>
                      <tr>
                        <td>与上一条已收录开奖的重号个数</td>
                        <td>{fmt(data.structure.mean_repeated, 2)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </Panel>
              <Panel title="号码分区" subtitle="按号码范围分成三段；理论均值按各区实际号码数量计算。">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>区间</th>
                        <th>总入选数</th>
                        <th>每期均值</th>
                        <th>理论均值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.regions.map((region) => (
                        <tr key={region.label}>
                          <td>{region.label}</td>
                          <td>{region.count}</td>
                          <td>{fmt(region.mean_per_draw, 2)}</td>
                          <td>{fmt(region.expected_per_draw, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
              <Panel
                title="两号码共现"
                subtitle={`同一期同时出现才计数，共 ${data.sample_size} 期。默认展示高频 20 组，仅为描述性排序，未做显著性判定。`}
              >
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>号码对</th>
                        <th>次数</th>
                        <th>频率</th>
                        <th>理论次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(showAllPairs ? pairs : pairs.slice(0, 20)).map((pair) => (
                        <tr key={pair.numbers.join('-')}>
                          <td>{pair.numbers.map((n) => String(n).padStart(2, '0')).join(' · ')}</td>
                          <td>{pair.count}</td>
                          <td>{pct(pair.frequency, 2)}</td>
                          <td>{fmt(pair.expected_count, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button className="text-button expand-tests" onClick={() => setShowAllPairs(!showAllPairs)}>
                  {showAllPairs ? '收起共现明细' : `查看全部 ${pairs.length} 组号码对`}
                </button>
              </Panel>
            </div>
          )}
          {tab === 'tests' && (
            <>
              <Panel
                title="运行一组有边界的检验"
                subtitle={
                  isDigit
                    ? '数字型按位做均匀性卡方检验（精确计算，无需零模型模拟）。'
                    : '包含整体频率、离散和值分布、单号频率、游程与序列相关。'
                }
              >
                <form
                  className="experiment-form"
                  onSubmit={(e) => {
                    e.preventDefault()
                    void experiment.launch({ window, trials })
                  }}
                >
                  {!isDigit && (
                    <label>
                      零模型模拟次数
                      <select value={trials} onChange={(e) => setTrials(Number(e.target.value))}>
                        <option value={999}>999 次（快速查看）</option>
                        <option value={4999}>4999 次</option>
                        <option value={9999}>9999 次</option>
                      </select>
                    </label>
                  )}
                  <div className="form-explainer">
                    {isDigit
                      ? '固定种子 2026。逐位卡方为精确计算，不走 Monte Carlo 模拟。'
                      : '固定种子 2026。对全部检验统一做 Bonferroni 校正；有限模拟的 p 值分辨率会影响检验功效。'}
                  </div>
                  <RunButton
                    pending={experiment.pending}
                    disabled={experiment.job?.status === 'running' || experiment.job?.status === 'queued'}
                    label="运行随机性检验"
                  />
                </form>
                <ErrorNote message={experiment.error} />
                <JobStatus job={experiment.job} />
              </Panel>
              {result && (
                <>
                  <div className="result-banner">
                    <Verdict value={result.verdict} />
                    <p>{result.interpretation}</p>
                  </div>
                  <div className="metric-strip">
                    <Metric label="检验样本" value={`${fmt(result.sample_size)} 期`} />
                    <Metric label="比较数量" value={result.number_of_tests} />
                    <Metric label="校正后显著项" value={result.significant_count} />
                    {!isDigit && <Metric label="零模型模拟" value={fmt(result.trials)} />}
                  </div>
                  <Panel
                    title="检验明细"
                    subtitle="p 值与效应大小应共同解读；显著偏离需要复核来源、规则和方法。"
                  >
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>检验</th>
                            <th>统计量</th>
                            <th>原始 p 值</th>
                            <th>校正后 p 值</th>
                            <th>结果</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(showAll
                            ? result.tests
                            : [...result.tests]
                                .sort((a, b) => a.adjusted_p_value - b.adjusted_p_value)
                                .slice(0, 12)
                          ).map((item) => (
                            <tr key={item.name}>
                              <td>
                                {item.name}
                                <small className="table-sub">{item.method}</small>
                              </td>
                              <td>{fmt(item.statistic, 4)}</td>
                              <td>{formatP(item.p_value)}</td>
                              <td>{formatP(item.adjusted_p_value)}</td>
                              <td>
                                <span
                                  className={`badge ${item.significant ? 'badge-review' : 'badge-neutral'}`}
                                >
                                  {item.significant ? '需要复核' : '未显著'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <button className="text-button expand-tests" onClick={() => setShowAll(!showAll)}>
                      {showAll ? '收起明细' : `查看全部 ${result.tests.length} 项`}
                    </button>
                    <div className="method-note">
                      {result.limitations.map((text) => (
                        <p key={text}>{text}</p>
                      ))}
                    </div>
                  </Panel>
                </>
              )}
              <History
                items={experiment.history.data?.items || []}
                active={experiment.active}
                onSelect={experiment.setActive}
              />
            </>
          )}
        </>
      )}
    </>
  )
}
export function formatP(value: number) {
  return value < 0.0001 && value > 0 ? value.toExponential(2) : value.toFixed(4)
}
