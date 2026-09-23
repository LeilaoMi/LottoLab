# 变更记录

记录已发布版本中影响使用和部署的变化。源码与固定版本下载见 [Releases](https://github.com/LeilaoMi/LottoLab/releases)。

## [1.1.1](https://github.com/LeilaoMi/LottoLab/releases/tag/v1.1.1) · 2026-09-24

安全与缺口收口版本（承接多源采集/快乐8期望/复盘只读，补齐 C5 安全项与 B 组前端缺口）：

- **限流先于鉴权**：`api_guards` 中间件先按 IP 计 POST 与重算类 GET（`/recommend`、`/verify`、`/optimizations`，默认 60 次/分，`LOTTOLAB_RATE_LIMIT_HEAVY_GETS_PER_MINUTE`）再做只读/写鉴权；失败鉴权的洪水同样消耗预算，`X-Forwarded-For` 受信链取最右一跳。
- **写权限补齐**：`POST /verify`、`POST /predictions` 走 `Depends(authorize)`；`GET /predictions/review?reconcile=true` 无写权限 403；中断任务自动过期清理仅写权限执行；`/api/*` 提前返回统一补 `X-Content-Type-Options`、`Referrer-Policy` 与 `frame-ancestors 'none'`。
- **采集 fail-closed**：`ingest_neon` / `refresh_winners` 生产写路径 HTTPS 空源不再回退明文 http；影子作业 17500 全量 https；全部移除 `curl --ssl-no-revoke`。
- **CSV 空附加区**：`special_numbers` 留空的行按空附加区导入（原 `int('')` 整行拒收）；本地备份目录 `0700`。
- **Settings 令牌校验**：短于 32 字符的 `admin_token` 在未启用本地写入时启动失败（与云端文档口径一致）。
- **CI actions 升 Node24**：`checkout@v6`、`setup-python@v6`、`setup-node@v6`、`upload-artifact@v6`、`pnpm/action-setup@v5`（ci / daily-sync / daily-winners / shadow-parallel）。
- **前端缺口**：彩种选择写入并校验 `localStorage`；空附加区不再渲染分隔线；CoverPage 目标命中上限 6；统计页附加区仅在有数据时出现、数字型隐藏误导性 trials；任务轮询瞬时失败退避重试；回测隐藏快乐8附加区 Brier；在线注数 min/max 对齐后端 clamp、验奖占位符彩种感知、胆拖文案；导入说明补“无附加区留空”。
- **回测 Precision@K**：分母改为 ticket_k（快乐8=10），与期望命中口径对齐。
- **多源采集修复**：同步按彩种路由官方接口（福彩 cwl `name=` / 体彩 `gameNo=`，不再 8 彩种全部 gameNo=85）；快乐8/福彩3D/排列三五/七星彩 影子作业补上第二源交叉；sporttery 需带站内 Referer。
- **在线工具注数**：七乐彩用 `main`、快乐8 用 `pick/nums`、数字型按位 `pos` 下发；组合覆盖对七乐彩按 7/30 规则取候选池（原误用 5/35）。
- **复盘 GET 只读**：`GET /predictions/review` 默认不写库，显式 `reconcile=true` 才对账（在线工具按钮传参）。
- **快乐8 期望命中**：票面 k=10、期望 = k×开奖球数/池，复盘/回测与推荐规则对齐（原误按 k=5/k² 退化）。
- **七乐彩评分**：复盘对账将特别号视为基本区命中（与验奖口径一致）。
- **随机建议公平性**：推荐破平局消费 seeded RNG，区间覆盖/附加区加确定性抖动，避免同种子总是同票。
- **样本外闸门**：冷门度流行度学习（含数字型）仅在 70/30 验证段与训练符号一致时通过，否则 fail-closed。
- **安全加固**：`X-Forwarded-For` 仅受信代理链生效（`LOTTOLAB_TRUSTED_PROXIES`）；缺 `Content-Length` 的 POST 拒绝；worker 错误信息脱敏；采集脚本去掉 `curl -k`；空源/分歧作业非零退出；GitHub Actions 加 concurrency、钉 `psycopg[binary]`。
- **回测稳定性对照**：测试窗前后半平均优势对照（CONSISTENT / INCONSISTENT / TOO_SHORT），纯描述性，不做检验、不参与 verdict；回测页新增对照列。
- **回测报告脚本**：`python scripts/export_report.py 报告.json` 把 JSON 导出渲染为 Markdown 摘要（打到控制台，自存 `.local/`，不进仓库）。

## [未发布]

## [1.1.0](https://github.com/LeilaoMi/LottoLab/releases/tag/v1.1.0) · 2026-09-18

8 彩种融合与安全加固版本（覆盖 8 个中国彩票，统一判定/验奖/注数/采集/推荐到单一后端）：

- **云端公开**：Vercel 部署默认公开模式，浏览与工作台免登录、不再弹令牌；设置至少 32 字符的 `LOTTOLAB_ADMIN_TOKEN` 后切为公开读、私有写（查询/推荐/验奖 GET 仍公开，同步/导入/回测等 POST 需令牌）。保留域名/来源/请求大小/并发等抗攻击护栏，验奖新增 GET 只读端点。自托管仍可选管理员令牌。
- **8 彩种数据**：POOL/DIGIT 域模型 + family-aware 约束；全量历史入库（约 3.6 万期）；开奖每日自动同步、真实一等奖注数/销量每日刷新（主源 17500，GitHub runner 可达）。
- **推荐升级**：7 策略（含冷门避撞）+ 结构分 + 全 8 彩种实测撞号指数 + 双色球冷门度（预计同奖人数/因子，移植并沿用样本外验证系数）；蓝球按策略多样化。
- **自证与闭环**：策略回测（滚动检验各策略命中≈随机）；预测复盘闭环（推荐落台账→开奖自动对账命中率/奖级）。
- **数字型研究**：逐位频率/遗漏 + 逐位均匀性卡方；七乐彩/快乐8 纳入深度研究（修复空附加区回测崩溃）。
- **注数与工具**：单式/复式/胆拖注数、批量验奖、票面 CSV 导出；仓库不再暴露线上域名。
- **诚实边界**：冷门度只对浮动奖有意义，仅双色球有验证系数（大乐透/七乐彩拟合后样本外不成立、不发布）；固定奖无分奖效应；一切不改变中奖概率。
- **冷门度拟合重做**：`fit_coldness` 销量正式做协变量（原占位系数），70/30 时序样本外符号一致 + 安慰剂 fail-closed；SSQ 已发布系数不变。配套离线拟合 CLI（`scripts/fit_coldness.py`，安慰剂注数需外配 CSV）。
- **复盘自动化**：每日同步后为双色球/大乐透生成推荐快照并登记台账（幂等，开奖后自动对账）；`scripts/snapshot_review.py`。
- **应用层限流**：POST /api/* 按 IP 滑动窗口（默认 120 次/分，可配可关）。
- **DLT 收益**：奖级版本化（2019-02-20 第19019期为界，6 奖级→9 奖级），回测、验奖、复盘三处统一口径；当期奖金表优先，固定奖缺数按版本常量回退（基本投注、税前）。
- **文档**：README 按现状重整（彩种矩阵/权限/限额/门禁），新增 API 速览。

## [1.0.0](https://github.com/LeilaoMi/LottoLab/releases/tag/v1.0.0) · 2026-09-13

首个稳定版本，提供完整的 SSQ / DLT 数据研究流程。

- 支持公开数据同步、CSV 导入导出、原始快照、质量报告和可追溯修订。
- 提供历史统计、无放回零模型、Monte Carlo 随机性检验和多重比较校正。
- 提供均匀随机、历史频率、逻辑回归、梯度提升树的时间回测，保存冻结数据和逐期结果。
- 提供随机模拟、条件收益计算、贪心组合覆盖和覆盖率区间。
- 提供八个中文页面、深色主题、移动端布局、实验状态和结果历史。
- 支持本地 SQLite、Docker / PostgreSQL，以及 Vercel + Neon 云端部署。
- 提供数据库迁移、本地备份与只读云备份；云备份包含独立恢复校验。

SSQ 收益计算依赖完整的历史奖级资料，DLT ROI 暂不提供。计算限制与方法边界见 [部署指南](docs/deployment.md) 和 [研究方法](docs/methodology.md)。
