import { ArrowRight, CheckCircle2, Download } from 'lucide-react'
import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fmt, pct, useExperiment, useResource } from '../api'
import type { BacktestResult } from '../api'
import {
  Balls,
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
import { formatP } from './Statistics'
import { useWorkspace } from '../Workspace'

const palette = ['#7e919e', '#39908c', '#366fa6', '#b66378']
const modelNames: Record<string, string> = {
  uniform: '均匀随机',
  frequency: '历史频率',
  logistic: '逻辑回归',
  gradient_boosting: '梯度提升树',
}

export function ModelsPage() {
  const catalog = useResource<{ items: { id: string; name: string; description: string; family: string }[] }>(
    '/models',
  )
  return (
    <>
      <PageTitle
        title="模型档案"
        description="先建立可靠基线，再检验复杂模型是否带来可复核的增益。"
        actions={
          <a className="button button-primary" href="#/backtest">
            进入滚动回测
            <ArrowRight size={16} />
          </a>
        }
      />
      <ErrorNote message={catalog.error} />
      {catalog.loading ? (
        <Loading />
      ) : (
        <Panel title="四个透明的对照对象" subtitle="模型使用同一份冻结数据、相同测试期次和相同选号预算。">
          <div className="model-catalog">
            {catalog.data?.items.map((model, index) => (
              <div className="model-entry" key={model.id}>
                <span className="model-color" style={{ background: palette[index] }} />
                <div>
                  <span className="badge badge-neutral">{model.family}</span>
                  <h3>{model.name}</h3>
                  <p>{model.description}</p>
                </div>
                <CheckCircle2 size={20} />
              </div>
            ))}
          </div>
        </Panel>
      )}
      <div className="grid-two">
        <Panel title="特征怎样生成">
          <div className="prose">
            <p>每期开始前，先对已公布的历史数据建立特征快照，再读取当期开奖结果作为训练标签。</p>
            <ul>
              <li>过去 10 / 30 / 100 期频率与累计频率</li>
              <li>截至上一期的遗漏，以及前两期是否出现</li>
              <li>固定号码位置，区分同一模型中的候选号码</li>
            </ul>
            <p>奖金、销量及当期结果不会进入预测特征。</p>
          </div>
        </Panel>
        <Panel title="概率与分数有不同含义">
          <div className="prose">
            <p>主区单号入选概率的总和等于每期抽取的号码数。双色球为 6，大乐透为 5。</p>
            <p>树模型和逻辑回归的输出会做基数一致性投影。这保证总和约束，不能证明概率已在样本外校准。</p>
            <p>校准图、Brier 分数和滚动回测负责检验模型输出，复杂程度本身不代表质量。</p>
          </div>
        </Panel>
      </div>
    </>
  )
}

export function BacktestPage() {
  const workspace = useWorkspace()
  const [testDraws, setTestDraws] = useState(120)
  const [training, setTraining] = useState(500)
  const [retrain, setRetrain] = useState(20)
  const [seed, setSeed] = useState(2026)
  const [models, setModels] = useState(['uniform', 'frequency', 'logistic', 'gradient_boosting'])
  const [selectedModel, setSelectedModel] = useState('frequency')
  const experiment = useExperiment<BacktestResult>(workspace, 'backtest', '/backtests')
  const result = experiment.job?.status === 'completed' ? experiment.job.result : null
  const model = result?.models.find((item) => item.model === selectedModel) || result?.models[0]
  const records = result?.records[model?.model || 'uniform'] || []
  const chart = result
    ? result.records.uniform.map((row) => {
        const point: Record<string, string | number> = { issue: row.issue }
        return point
      })
    : []
  if (result) {
    const cumulative: Record<string, number> = {}
    result.models.forEach((item) => {
      cumulative[item.model] = 0
    })
    chart.forEach((point, index) =>
      result.models.forEach((item) => {
        cumulative[item.model] += result.records[item.model][index].main_brier
        point[item.model] = cumulative[item.model] / (index + 1)
      }),
    )
  }
  function download() {
    if (!result) return
    const url = URL.createObjectURL(
      new Blob([JSON.stringify({ job: experiment.job, result }, null, 2)], { type: 'application/json' }),
    )
    const link = document.createElement('a')
    link.href = url
    link.download = `lottolab-backtest-${experiment.active?.slice(0, 8)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }
  return (
    <>
      <PageTitle title="滚动回测" description="沿着历史时间向前走，每次预测只使用此前已经公布的信息。" />
      <Panel title="设置同一场对照实验" subtitle="均匀随机基线始终保留；测试区间为冻结数据中最后若干期。">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void experiment.launch({
              models,
              test_draws: testDraws,
              training_window: training,
              retrain_every: retrain,
              seed,
            })
          }}
        >
          <div className="form-grid">
            <label>
              测试期数
              <input
                type="number"
                min={20}
                max={400}
                required
                value={testDraws}
                onChange={(e) => setTestDraws(Number(e.target.value))}
              />
            </label>
            <label>
              训练窗口上限
              <input
                type="number"
                min={80}
                max={1500}
                required
                value={training}
                onChange={(e) => setTraining(Number(e.target.value))}
              />
            </label>
            <label>
              每隔多少期重训
              <input
                type="number"
                min={5}
                max={100}
                required
                value={retrain}
                onChange={(e) => setRetrain(Number(e.target.value))}
              />
            </label>
            <label>
              随机种子
              <input
                type="number"
                min={0}
                max={2147483647}
                required
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="model-options">
            {Object.entries(modelNames).map(([id, label], index) => (
              <label key={id}>
                <input
                  type="checkbox"
                  checked={models.includes(id)}
                  disabled={id === 'uniform'}
                  onChange={(e) =>
                    setModels(e.target.checked ? [...models, id] : models.filter((value) => value !== id))
                  }
                />
                <i style={{ background: palette[index] }} />
                {label}
              </label>
            ))}
          </div>
          <div className="form-footer">
            <p>主指标：主区平均 Brier，越低越好。参数固定，不使用测试集调参。</p>
            <RunButton
              pending={experiment.pending}
              disabled={experiment.job?.status === 'running' || experiment.job?.status === 'queued'}
              label="开始滚动回测"
            />
          </div>
        </form>
        <ErrorNote message={experiment.error} />
        <JobStatus job={experiment.job} />
      </Panel>
      {result && (
        <>
          <div className="result-heading">
            <div>
              <h2>本次回测结果</h2>
              <p>
                第 {result.start_issue} – {result.end_issue} 期 · 数据版本{' '}
                {experiment.job?.dataset_id?.slice(0, 12)}
              </p>
            </div>
            <button className="button" onClick={download}>
              <Download size={16} />
              导出完整报告
            </button>
          </div>
          <div className="metric-strip">
            <Metric label="测试期数" value={result.sample_size} />
            <Metric label="比较模型" value={result.models.length} />
            <Metric label="实际拟合次数" value={result.fit_events.length} />
            <Metric label="特征版本" value="v1" note="严格使用历史快照" />
          </div>
          <Panel
            title="模型与基线"
            subtitle="优势值为随机基线 Brier 减去模型 Brier；正数表示该样本中的损失更低。"
          >
            <div className="table-wrap">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>模型</th>
                    <th>主区 Brier ↓</th>
                    <th>平均命中</th>
                    <th>优势与 95% 区间</th>
                    <th>校正后 p 值</th>
                    <th>判定</th>
                    <th>前后半对照</th>
                  </tr>
                </thead>
                <tbody>
                  {result.models.map((item) => (
                    <tr key={item.model}>
                      <td className="strong">{item.name}</td>
                      <td>{item.metrics.main_brier.toFixed(5)}</td>
                      <td>{item.metrics.main_hits.toFixed(3)}</td>
                      <td>
                        {item.comparison ? (
                          <>
                            {item.comparison.delta.toFixed(5)}
                            <small className="table-sub">
                              [{item.comparison.confidence_interval.map((v) => v.toFixed(5)).join(', ')}]
                            </small>
                          </>
                        ) : (
                          '参照值'
                        )}
                      </td>
                      <td>{item.comparison ? formatP(item.comparison.adjusted_p_value) : '—'}</td>
                      <td>
                        <Verdict value={item.verdict} />
                      </td>
                      <td>
                        {item.stability ? (
                          <>
                            {item.stability.verdict === 'CONSISTENT'
                              ? '一致'
                              : item.stability.verdict === 'INCONSISTENT'
                                ? '不一致'
                                : '样本不足'}
                            {item.stability.first_half != null && item.stability.second_half != null && (
                              <small className="table-sub">
                                [{item.stability.first_half.toFixed(5)},{' '}
                                {item.stability.second_half.toFixed(5)}]
                              </small>
                            )}
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="method-note">
              {result.comparison_method}。{result.stability_method}。本次结果不构成对未来预测能力的保证。
            </div>
          </Panel>
          <Panel title="累计平均 Brier" subtitle="比较相同测试期次内的累计损失，不以某一期命中代替长期评价。">
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <LineChart data={chart}>
                  <CartesianGrid strokeDasharray="3 4" vertical={false} />
                  <XAxis dataKey="issue" minTickGap={70} />
                  <YAxis width={48} domain={['auto', 'auto']} tickFormatter={(n) => Number(n).toFixed(3)} />
                  <Tooltip formatter={(value) => Number(value).toFixed(5)} />
                  <Legend />
                  {result.models.map((item, i) => (
                    <Line
                      isAnimationActive={false}
                      key={item.model}
                      dataKey={item.model}
                      name={item.name}
                      stroke={palette[i]}
                      dot={false}
                      strokeWidth={1.8}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Panel>
          <Panel
            title="查看一个模型的细节"
            action={
              <select
                aria-label="查看模型细节"
                value={model?.model}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {result.models.map((item) => (
                  <option key={item.model} value={item.model}>
                    {item.name}
                  </option>
                ))}
              </select>
            }
          >
            {model && (
              <>
                <div className="metric-strip compact">
                  <Metric label="主区二元 Log Loss" value={fmt(model.metrics.main_log_loss, 5)} />
                  {workspace.lottery !== 'kl8' && (
                    <Metric label="附加区 Brier" value={fmt(model.metrics.special_brier, 5)} />
                  )}
                  <Metric label="Precision@K" value={pct(model.metrics.precision_at_k, 2)} />
                  <Metric
                    label="税前模拟 ROI"
                    value={pct(model.roi, 2)}
                    note={model.roi == null ? '缺少适用派奖数据，未计算' : '按历史每注奖金，未重算分奖'}
                  />
                </div>
                <div className="grid-two detail-grid">
                  <div>
                    <h3>主区概率校准观察</h3>
                    <div className="chart chart-small">
                      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                        <ScatterChart>
                          <CartesianGrid strokeDasharray="3 4" />
                          <XAxis dataKey="predicted" type="number" domain={[0, 1]} name="模型概率" />
                          <YAxis
                            dataKey="observed"
                            type="number"
                            domain={[0, 1]}
                            width={35}
                            name="实际频率"
                          />
                          <Tooltip cursor={{ strokeDasharray: '3 3' }} />
                          <ReferenceLine
                            segment={[
                              { x: 0, y: 0 },
                              { x: 1, y: 1 },
                            ]}
                            stroke="#93a8b6"
                            strokeDasharray="5 4"
                          />
                          <Scatter isAnimationActive={false} data={model.calibration} fill="#397d9f" />
                        </ScatterChart>
                      </ResponsiveContainer>
                    </div>
                    <p className="small-note">
                      横轴为平均模型概率，纵轴为该区间实际出现频率。靠近对角线表示这份样本中较一致。
                    </p>
                  </div>
                  <div>
                    <h3>最近 8 期预测记录</h3>
                    <div className="prediction-list">
                      {records
                        .slice(-8)
                        .reverse()
                        .map((row) => (
                          <div key={row.issue}>
                            <span>{row.issue}</span>
                            <Balls main={row.main_ticket} special={row.special_ticket} compact />
                            <small>
                              命中 {row.main_hits}+{row.special_hits}
                            </small>
                          </div>
                        ))}
                    </div>
                  </div>
                </div>
              </>
            )}
          </Panel>
          <Panel title="复现信息与解释边界">
            <div className="prose">
              <p>
                代码指纹：<code>{result.code_fingerprint.slice(0, 20)}</code>　特征：
                <code>{result.feature_version}</code>
              </p>
              <ul>
                {result.limitations.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
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
  )
}
