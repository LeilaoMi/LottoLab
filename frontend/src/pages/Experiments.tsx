import { BookOpen, Download } from 'lucide-react'
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
import { fmt, pct, useExperiment } from '../api'
import type { CoverResult, SimulationResult } from '../api'
import { ErrorNote, History, JobStatus, Metric, PageTitle, Panel, RunButton, Tickets } from '../components'
import { useWorkspace } from '../Workspace'

export function SimulationPage() {
  const workspace = useWorkspace()
  const [iterations, setIterations] = useState(100000)
  const [seed, setSeed] = useState(2026)
  const experiment = useExperiment<SimulationResult>(workspace, 'simulation', '/simulations')
  const result = experiment.job?.status === 'completed' ? experiment.job.result : null
  return (
    <>
      <PageTitle title="随机模拟" description="用可复现的模拟理解命中分布，和精确组合概率相互核对。" />
      <Panel
        title="让随机性成为参照"
        subtitle="固定一注合法组合，与独立均匀开奖比较。这个实验不依赖历史数据。"
      >
        <form
          className="experiment-form"
          onSubmit={(e) => {
            e.preventDefault()
            void experiment.launch({ iterations, seed })
          }}
        >
          <label>
            模拟次数
            <select value={iterations} onChange={(e) => setIterations(Number(e.target.value))}>
              <option value={10000}>10,000 次</option>
              <option value={100000}>100,000 次</option>
              <option value={1000000}>1,000,000 次</option>
            </select>
          </label>
          <label>
            随机种子
            <input
              type="number"
              value={seed}
              min={0}
              max={2147483647}
              onChange={(e) => setSeed(Number(e.target.value))}
              required
            />
          </label>
          <div className="form-explainer">
            相同参数与运行环境会产生相同结果。显示模拟波动，同时保留精确理论值。
          </div>
          <RunButton
            pending={experiment.pending}
            disabled={experiment.job?.status === 'running' || experiment.job?.status === 'queued'}
            label="开始模拟"
          />
        </form>
        <ErrorNote message={experiment.error} />
        <JobStatus job={experiment.job} />
      </Panel>
      {result ? (
        <>
          <div className="metric-strip">
            <Metric label="模拟次数" value={fmt(result.iterations)} />
            <Metric
              label="主区平均命中"
              value={fmt(result.mean_hits, 4)}
              note={`理论期望 ${fmt(result.expected_hits, 4)}`}
            />
            <Metric
              label="平均命中 95% 区间"
              value={`${fmt(result.mean_confidence_interval[0], 3)} – ${fmt(result.mean_confidence_interval[1], 3)}`}
            />
            <Metric label="全中次数" value={result.jackpots} note="有限模拟可能一次也不出现" />
          </div>
          <Panel title="命中分布：模拟与理论" subtitle="横轴为一注命中的主区号码数，纵轴为该事件比例。">
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <ComposedChart data={result.distribution}>
                  <CartesianGrid strokeDasharray="3 4" vertical={false} />
                  <XAxis dataKey="hits" />
                  <YAxis width={45} tickFormatter={(value) => pct(Number(value), 0)} />
                  <Tooltip formatter={(value) => pct(Number(value), 4)} />
                  <Legend />
                  <Bar
                    isAnimationActive={false}
                    dataKey="observed"
                    name="模拟比例"
                    fill="#7eafbe"
                    maxBarSize={70}
                    radius={[4, 4, 0, 0]}
                  />
                  <Line
                    isAnimationActive={false}
                    dataKey="theoretical"
                    name="精确理论概率"
                    stroke="#b56378"
                    strokeWidth={2}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Panel>
          <div className="grid-two">
            <Panel title="完整组合的极小概率">
              <div className="probability-note">
                <span>精确全中概率</span>
                <strong>1 / {fmt(Math.round(1 / result.jackpot_probability))}</strong>
                <p>{result.note}</p>
                <small>
                  本次全中事件的 95% Wilson 区间：{pct(result.jackpot_confidence_interval[0], 6)} –{' '}
                  {pct(result.jackpot_confidence_interval[1], 6)}
                </small>
              </div>
            </Panel>
            <Panel title="模拟不能替代精确计算">
              <div className="prose">
                <p>
                  一百万次模拟仍可能看不到一次头奖。用“观察到的次数 ÷
                  模拟次数”直接估计这种极小概率，误差会很大。
                </p>
                <p>
                  因此平台对全中概率使用组合公式，对常见的部分命中事件再用模拟验证。未观察到事件，不等于事件不可能发生。
                </p>
              </div>
            </Panel>
          </div>
        </>
      ) : (
        <Panel>
          <div className="simulation-intro">
            <div className="sample-balls">
              {[0, 1, 2, 3, 4, 5, 6].map((value, index) => (
                <div key={value}>
                  <i style={{ height: `${[24, 80, 45, 18, 9, 5, 3][index]}px` }} />
                  <span>{value}</span>
                </div>
              ))}
            </div>
            <h3>先理解随机，才有可靠的比较</h3>
            <p>开始模拟，查看部分命中的常见程度，以及有限样本会带来多大的波动。</p>
          </div>
        </Panel>
      )}
      <History
        items={experiment.history.data?.items || []}
        active={experiment.active}
        onSelect={experiment.setActive}
      />
    </>
  )
}

export function CoverPage() {
  const workspace = useWorkspace()
  const coverRule =
    workspace.lottery === 'ssq'
      ? { maximum: 33, chosen: 6, initial: [1, 3, 5, 7, 9, 12, 15, 18, 22, 25, 29, 33] }
      : workspace.lottery === 'qlc'
        ? { maximum: 30, chosen: 7, initial: [1, 3, 5, 7, 9, 12, 15, 18, 22, 25, 28, 30] }
        : { maximum: 35, chosen: 5, initial: [1, 3, 5, 7, 9, 12, 15, 18, 22, 25, 29, 33] }
  const { maximum, chosen, initial } = coverRule
  const [pool, setPool] = useState(initial)
  const [count, setCount] = useState(10)
  const [target, setTarget] = useState(3)
  const [seed, setSeed] = useState(2026)
  const experiment = useExperiment<CoverResult>(workspace, 'covering', '/optimizations/covering')
  const result = experiment.job?.status === 'completed' ? experiment.job.result : null
  function toggle(n: number) {
    setPool((values) =>
      values.includes(n)
        ? values.filter((v) => v !== n)
        : values.length < 18
          ? [...values, n].sort((a, b) => a - b)
          : values,
    )
  }
  function download() {
    if (!result) return
    const text =
      'main_numbers,special_numbers\n' +
      result.tickets.map((row) => `${row.main_numbers.join(' ')},${row.special_numbers.join(' ')}`).join('\n')
    const url = URL.createObjectURL(new Blob(['\ufeff' + text], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `lottolab-cover-${experiment.active?.slice(0, 8)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }
  return (
    <>
      <PageTitle
        title="组合覆盖实验"
        description="给定候选范围和注数，研究如何减少重复、扩大主区组合覆盖。"
      />
      <Panel
        title="定义候选范围"
        subtitle={`已选 ${pool.length} 个号码；至少 ${chosen} 个，最多 18 个。候选集是你的输入，不是模型推荐。`}
      >
        <div className="candidate-grid">
          {Array.from({ length: maximum }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              aria-label={`候选号码 ${n}`}
              aria-pressed={pool.includes(n)}
              className={pool.includes(n) ? 'selected' : ''}
              disabled={!pool.includes(n) && pool.length >= 18}
              onClick={() => toggle(n)}
            >
              {String(n).padStart(2, '0')}
            </button>
          ))}
        </div>
        <form
          className="experiment-form"
          onSubmit={(e) => {
            e.preventDefault()
            void experiment.launch({
              candidate_numbers: pool,
              ticket_count: count,
              target_hits: target,
              seed,
              samples: 20000,
            })
          }}
        >
          <label>
            组合注数
            <input
              type="number"
              min={1}
              max={40}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              required
            />
          </label>
          <label>
            主区目标命中
            <select value={target} onChange={(e) => setTarget(Number(e.target.value))}>
              {Array.from({ length: Math.min(chosen, 6) }, (_, i) => i + 1).map((n) => (
                <option value={n} key={n}>
                  至少 {n} 个
                </option>
              ))}
            </select>
          </label>
          <label>
            随机种子
            <input
              type="number"
              value={seed}
              min={0}
              max={2147483647}
              onChange={(e) => setSeed(Number(e.target.value))}
              required
            />
          </label>
          <RunButton
            pending={experiment.pending}
            disabled={
              pool.length < chosen ||
              experiment.job?.status === 'running' ||
              experiment.job?.status === 'queued'
            }
            label="计算覆盖方案"
          />
        </form>
        <div className="method-note">
          目标只衡量主区命中，不包含附加区，也不代表某个中奖奖级。基础单式数学成本为每注 2
          元，平台不会执行购彩。
        </div>
        <ErrorNote message={experiment.error} />
        <JobStatus job={experiment.job} />
      </Panel>
      {result && (
        <>
          <div className="notice notice-demo">{result.condition}</div>
          <div className="metric-strip">
            <Metric
              label="目标子集覆盖"
              value={pct(result.tuple_coverage)}
              note={`${fmt(result.covered_tuples)} / ${fmt(result.total_tuples)} 个子集`}
            />
            <Metric
              label="候选池内主区覆盖"
              value={pct(result.conditional_main_coverage)}
              note={`精确枚举 ${fmt(result.conditional_draws_total)} 个开奖组合`}
            />
            <Metric
              label="完整主区空间覆盖"
              value={pct(result.unconditional_main_coverage)}
              note={`模拟 95% 区间 ${pct(result.unconditional_confidence_interval[0])}–${pct(result.unconditional_confidence_interval[1])}`}
            />
            <Metric
              label="数学成本"
              value={`¥${result.cost}`}
              note={`子集重复度 ${pct(result.duplicate_tuple_fraction)}`}
            />
          </div>
          <div className="grid-two">
            <Panel
              title="组合方案"
              subtitle="附加区为随机样例，不参与当前覆盖目标。"
              action={
                <button className="button" onClick={download}>
                  <Download size={15} />
                  导出组合
                </button>
              }
            >
              <Tickets tickets={result.tickets} />
            </Panel>
            <Panel title="每增加一注的覆盖变化">
              <div className="chart">
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <ComposedChart data={result.gains}>
                    <CartesianGrid strokeDasharray="3 4" vertical={false} />
                    <XAxis dataKey="tickets" />
                    <YAxis width={42} />
                    <Tooltip />
                    <Legend />
                    <Bar isAnimationActive={false} dataKey="new_tuples" name="新增子集" fill="#a2c4ce" />
                    <Line
                      isAnimationActive={false}
                      dataKey="covered_tuples"
                      name="累计覆盖"
                      stroke="#326f9e"
                      strokeWidth={2}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="method-note">{result.limitations}</div>
            </Panel>
          </div>
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

export function MethodologyPage() {
  return (
    <>
      <PageTitle title="研究方法与边界" description="知道每个数字是怎样得到的，也知道它不能说明什么。" />
      <section className="method-intro">
        <BookOpen size={32} />
        <div>
          <h2>用证据回答问题，保留不确定性</h2>
          <p>
            LottoLab
            是数据与概率实验室。历史记录、统计结果、模型输出和组合覆盖分别回答不同问题，不能互相替代。
          </p>
        </div>
      </section>
      <Panel title="一场避免偷看答案的回测">
        <ol className="method-flow">
          {[
            '读取已公布历史',
            '冻结当期特征',
            '仅在训练期拟合',
            '生成当期预测',
            '读取真实结果',
            '与基线统一比较',
          ].map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ol>
        <div className="prose">
          <p>
            标准化、参数拟合和概率处理也属于训练过程，必须遵守同一时间边界。系统用未来数据扰动测试，检查过去的特征和预测是否会受到影响。
          </p>
        </div>
      </Panel>
      <div className="method-grid">
        <Panel title="独立均匀是零模型">
          <div className="prose">
            <p>
              以合法组合独立、均匀为比较基准。双色球单个红球入选概率是 6/33；完整组合概率为 1/[C(33,6)×16]。
            </p>
            <p>
              历史出现次数高或遗漏时间长，不会在这个模型下改变下一期概率。物理过程是否有偏离，需要用数据检验，不能事先假定结论。
            </p>
          </div>
        </Panel>
        <Panel title="一期内部不能当独立抽球">
          <div className="prose">
            <p>主区号码是不放回抽样。命中数、奇偶个数等服从相应的超几何分布，和值也有自己的组合分布。</p>
            <p>因此，系统用完整无放回零模型校准整体统计量，不把所有号码当作相互独立的观测。</p>
          </div>
        </Panel>
        <Panel title="p 值需要放回上下文">
          <div className="prose">
            <p>p 值描述零假设下观察到相同或更极端结果的可能性，不是“这个规律为真的概率”。</p>
            <p>
              同时检验很多号码或策略会增加偶然发现。本平台显示原始与校正后 p
              值；未显著不能证明绝对随机，显著也不能直接证明可预测。
            </p>
          </div>
        </Panel>
        <Panel title="模型的参照是随机基线">
          <div className="prose">
            <p>“命中了几个号码”本身不足以说明模型有效。双色球随机选六个红球，平均也会命中约 1.09 个。</p>
            <p>概率输出主要比较 Brier 与二元 Log Loss。模型越复杂并不一定越好，负结果会同样保存。</p>
          </div>
        </Panel>
        <Panel title="覆盖率一定要说明分母">
          <div className="prose">
            <p>候选池中的 100% 条件覆盖，不等于完整开奖空间的 100% 覆盖。</p>
            <p>
              本平台分别报告目标子集覆盖、候选池内主区覆盖和完整主区空间的模拟覆盖。附加区不参与当前优化目标，不宣传保底中奖。
            </p>
          </div>
        </Panel>
        <Panel title="收益是带假设的模拟">
          <div className="prose">
            <p>
              有适用历史派奖数据时，才计算税前的基础单式模拟收益。不会用一个固定头奖或行业返奖率填补缺失数据。
            </p>
            <p>
              计算不重算新增投注对同奖注数的影响。演示数据与当前 DLT 实验不输出 ROI，不能据此宣称实际盈利。
            </p>
          </div>
        </Panel>
        <Panel title="反复试验也是选择偏差">
          <div className="prose">
            <p>单次回测中的多模型比较做校正，但反复更换窗口、种子、参数，再只挑最好结果，仍然会产生偏差。</p>
            <p>
              应预先定义主要问题和指标，保留全部记录，并用独立时间段复核。当前功能没有自动进行跨所有历史实验的全局校正。
            </p>
          </div>
        </Panel>
        <Panel title="数据来源与可复现">
          <div className="prose">
            <p>
              公开数据优先来自中国福彩/中国体彩，备用来源为 500
              公开数据。所有入库记录经过数量、范围、去重与日期校验。
            </p>
            <p>
              原始响应保存校验值。实验冻结数据版本，记录种子、参数、代码指纹与依赖版本；覆盖范围按实际收录报告。
            </p>
          </div>
        </Panel>
      </div>
    </>
  )
}
