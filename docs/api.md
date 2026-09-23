# API 速览

[首页](../README.md) / API 速览

所有响应均为 JSON。`lottery` 取值 `ssq dlt qlc kl8 fc3d pl3 pl5 qxc`；`dataset_kind` 取值 `real synthetic`。错误形如 `{"detail": "原因"}`；`/api/` 响应均带 `Cache-Control: no-store`。

## 鉴权与限流

| 方法 | 默认 | 说明 |
| :--- | :--- | :--- |
| GET | 公开 | 私有部署（`LOTTOLAB_REQUIRE_READ_AUTH=true`）下需令牌；`health/rules/models` 始终公开 |
| POST | 需写权限 | 本机回环 + 允许本地写入，或 `X-Admin-Token`；云端未设令牌时公开，设令牌后需令牌（已设令牌不足 32 字符启动失败） |

写请求按 IP 滑动窗口限流（默认 120 次/分，`LOTTOLAB_RATE_LIMIT_POSTS_PER_MINUTE`，0 关闭），超限 429。`X-Forwarded-For` 仅在直连地址为受信代理（回环/内网或 `LOTTOLAB_TRUSTED_PROXIES`）时采用；缺 `Content-Length` 的 POST 直接 413。CSV 另有大小限制（本地 8 MiB / 云端 4 MiB）。

## 只读

| 路径 | 参数 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/health` | — | 状态、版本、数据库、worker、读写权限与限额 |
| `/api/v1/rules` | — | 8 彩种规则、组合数与理论概率 |
| `/api/v1/models` | — | 回测四模型目录 |
| `/api/v1/overview` | lottery, dataset_kind | 总量、起止日期、最新开奖、来源、质量计数与近 100 期统计 |
| `/api/v1/draws/latest` | lottery, dataset_kind | 最新一期 |
| `/api/v1/draws` | lottery, dataset_kind, offset, limit(≤200), search, start_date, end_date | 分页查询 |
| `/api/v1/draws/{issue}` | lottery, dataset_kind | 单期查询 |
| `/api/v1/draws/export` | lottery, dataset_kind | CSV 导出（含奖金 JSON） |
| `/api/v1/statistics/frequency` | lottery, dataset_kind, window(10–3000) | 频率/遗漏/形态汇总 |
| `/api/v1/statistics/omission` | 同上 | 同一处理器 |
| `/api/v1/bet` | kind, p(JSON) | 纯注数/金额计算，不读库 |
| `/api/v1/verify` | kind, lines(换行分隔), codes(逗号分隔) | 只读验奖，单次 200 注×10 期 |
| `/api/v1/recommend` | kind, seed, groups(≤8) | 多策略推荐 + 结构分/撞号/冷门度 |
| `/api/v1/recommend/backtest` | kind, window(20–300) | 各策略滚动回测 vs 均匀期望 |
| `/api/v1/predictions/review` | kind, reconcile(默认 false) | 台账只读汇总；`reconcile=true` 才触发对账写库 |
| `/api/v1/ingestions` | lottery, dataset_kind | 最近 50 次导入记录 |
| `/api/v1/quality` | lottery, dataset_kind | 未处理质量问题（含冲突双方） |
| `/api/v1/jobs` | lottery, dataset_kind, kind | 最近 40 个任务（不含完整结果） |
| `/api/v1/jobs/{job_id}` | — | 任务详情（含结果）；`/api/v1/backtests/{job_id}` 同处理器 |

## 写入（202 Accepted 为异步任务）

| 路径 | 内容 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/sources/sync` | lottery, dataset_kind=real, count(30–3000) | 同步公开来源 |
| `/api/v1/datasets/demo` | lottery, count(100–3000) | 生成合成演示数据（`SIM-` 期号） |
| `/api/v1/imports/csv` | multipart file + lottery + dataset_kind | CSV 导入并校验 |
| `/api/v1/quality/{issue_id}/resolve` | keep_existing / accept_incoming + 哈希 | 冲突复核（乐观并发） |
| `/api/v1/statistics/randomness` | window(30–1000), trials(999–9999) | 随机性检验 |
| `/api/v1/backtests` | models, test_draws(20–400), training_window(80–1500), retrain_every, bootstrap_samples | 时间回测 |
| `/api/v1/simulations` | iterations(1千–100万) | Monte Carlo 模拟 |
| `/api/v1/optimizations/covering` | candidate_numbers(5–18), ticket_count(≤40), target_hits, samples | 贪心组合覆盖 |
| `/api/v1/strategies/generate` | lottery, count(≤40), strategy | 按策略生成票面 |
| `/api/v1/verify` | kind, lines[], codes[] | 批量验奖（POST 版，与 GET 同判定） |
| `/api/v1/predictions` | kind, target_issue, picks[], seed | 推荐落台账 |
| `/api/v1/jobs/{job_id}/cancel` | — | 取消排队/运行中任务 |

任务状态：`queued running completed failed cancelled`；`GET /api/v1/jobs` 不含完整结果，详情走单任务接口。云端按请求执行（最多 1 项、240 秒），本地/Docker 由独立 worker 顺序执行（合计最多 8 项）。
