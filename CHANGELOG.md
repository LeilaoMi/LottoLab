# 变更记录

记录已发布版本中影响使用和部署的变化。源码与固定版本下载见 [Releases](https://github.com/LeilaoMi/LottoLab/releases)。

## [未发布]

### 修正 · README 的「多源交叉校验」承诺与生产写入路径不符（2026-09-30）

逐行核实后发现：README 三条立场里的「多源交叉校验，不一致的期号拒绝入库」**对影子表成立、对生产表不成立**。

- `collector/daily_sync.py` 是单源 append（硬编码 `source="17500"`，从不 import `collect_core.ingest`）
- 带多源语义指纹比对（`records_by_source` → `accepted`/`rejected`）的逻辑只在 `collector/shadow_parallel.py`，
  而影子的 `DIVERGE → sys.exit(1)` 触发 Actions 告警、**不阻止**行进入 `draws`
- 线上 23 条 `ingestion_runs` 的 `source` 全是单值，`conflicts` 合计 0

这不是代码缺陷被掩盖，而是**文档承诺与执行路径脱节**——201 项测试全绿的情况下长期存在，因为没有任何测试检查 README 的断言对应哪条代码路径。修法分三步：

1. **README 改说实话**：立场改为「号码多源比对在影子层运行，分歧即告警（不拦生产写入）」，并加更正说明写清范围与后续兑现路径
2. **`ingestion_runs` 增加 `sources_cross_checked`**（迁移 `x2srcval01`）：`conflicts=0` 无法区分「比对过且一致」与「压根没比对」，这一列才是判据。
   历史行全部回填 `false` —— 按 `true` 回填等于凭空造出一批从未发生过的校验记录。
   `daily_sync.py` 显式写 `sources_cross_checked=False`（不写也不会跑错，但写出来是为了不让 `conflicts=0` 被误读成「比对过」）
3. **新增 `tests/test_readme_claims.py`**（10 项）：承诺 ↔ 代码路径对账门禁。检查 daily_sync 是否仍为单源、影子作业是否越权写 `draws`、
   `sources_cross_checked` 是否同时存在于模型/迁移/API 三处、README 是否仍声称「拒绝入库」、
   **并实际执行 `collect_core.ingest` 证明冲突确实被拒绝、单源确实被放行**
   （后者是 README 更正说明的代码依据：`ingest` 对单源也放行，所以「过了 ingest」不能证明「经过多源校验」）

### 修正 · 架构图标注 PWA 但仓库无 manifest 与 Service Worker（2026-09-30）

README 架构图写「React 单页 · 9 页面 / PWA / 深色 / 移动端」。实测：全仓库 `manifest*.json` 0 个、
`sw.js` / `service-worker.*` 0 个。深色与移动端属实（有 e2e 覆盖），**PWA 不属实**。
架构图已改为「深色 / 移动端（无 PWA：未接 manifest / Service Worker）」。门禁测试会在将来真正接入 PWA 时自动通过。

### 补强 · 显式警示 Vercel 未设令牌即开放写端点（2026-09-30）

原访问表只写「Vercel 未设令牌 → 公开可访问（无需登录）」，容易被读成一句无害的默认值。已补警示：

- `cloud.py` 的逻辑是「令牌 ≥32 位 → 鉴权；未设或不足 → `public_mode=True`」，
  也就是不设令牌等于对互联网开放 12 个写端点（含 CSV 导入与触发重算）
- 本地 / Docker 不受影响：`public_mode` 与 `allow_local_writes` 默认均 `False`，未授权写入一律 403
- 限流按进程计数（`ratelimit.py` 自述「treat this as a backstop, not a quota」），
  Vercel 多实例下防护弱于看起来的强度，不应依赖限流兜底

### 补测 · 数据契约（`contract.py`）从 0% 覆盖到 98%（2026-09-30）

实测覆盖率：backend 85%、collector 9%，合并 74%。缺口集中在 `contract.py`（0%），
而它是 **8 个彩种号池规则的唯一事实源** —— 采集器与影子作业都 import 它，
落库前每一注「合不合规」都走它。一处写错（例如把 qxc 末位号池写成 0..9）
会让真实开奖号被静默计入 `rejected` 丢弃，而 201 项测试全绿。

新增 `tests/test_contract_rules.py`（52 项，纯标准库、离线）：

- **qxc 末位号池 0..14**（契约里唯一「某位号池不等于其它位」的情形），前 6 位仍 0..9
- 池型必须排序、不可重复；数字型必须保持顺序、允许重号（排序会破坏组三/豹子形态判定）
- qlc 特别号 1..30 且不得与基本号重复；kl8 无辅区
- 期号归一：5 位补 `20`、qxc 保持 5 位、年内期次须 ∈1..366、期号年份须与开奖日期一致
- 指纹语义：池型与输入顺序无关、数字型与顺序有关、同号码不同日期算矛盾
- **采集层契约与后端领域模型对账**：两处各自定义 8 彩种规则，只改一边会让数据在落库前
  被一边悄悄拒掉而两边单测都还绿

三个变异测试确认断言有效：qxc 末位写成 9 → 挂 2 项；数字型误加 `sorted()` → 挂 3 项；
去掉 qlc 特别号去重 → 挂 1 项。

### 门禁 · CI 加覆盖率下限（2026-09-30）

CI 此前装了 `pytest-cov` 却不加 `--cov`、无 `fail_under`。现加
`--cov=backend --cov=collector --cov-fail-under=74`，并把 `coverage.xml` 一起归档。

**只对合并值设门禁、不分列设**：分列看差异极大（backend 85% / collector 9%），
但合并后统计层的高覆盖会稀释掉采集层的低覆盖。分列设会逼着人把 collector 抬到 85%，
那不是靠补测试一轮能做到的。74% 是当前真实水平，门禁的作用是「不许再掉」。

### 工程 · 若干小项（2026-09-30）

- `daily-winners.yml` 补 `concurrency`（另两个每日作业原先都有；手动触发与定时触发
  同时发生会并行写同一批 prizes/sales 行）
- `docker/Dockerfile` 补 `HEALTHCHECK`（此前健康检查只在 compose.yaml，裸 `docker run` 拿不到）
- 新增 `.github/dependabot.yml`（pip 合成一个 PR / npm / github-actions 三档）
- 补 `v1.0.0` 的 GitHub release 条目（tag 与 CHANGELOG 文档都在，缺 release 入口）

### 修复 · 镜像级 HEALTHCHECK 让 CI container job 变红（2026-09-30，同日自查发现）

上一条「给 Dockerfile 补 HEALTHCHECK」是个**我自己引入的回归**，由本次提交的 CI 抓出来：

给 `docker/Dockerfile` 加了一条打 `/api/v1/health` 的镜像级健康检查后，CI 的 container job
第 6 步 `docker compose up -d --build --wait` 失败于
`container lottolab-ci-worker-1 is unhealthy`（exit 1）。

**根因**：`compose.yaml` 里 worker 只写 `image: lottolab:local`、没有 `build:`，所以 worker
与 api **共用同一个镜像**；而 worker 跑 `python -m lottolab.worker` —— 长驻进程、容器内
没有 8000 端口的服务。那条面向 HTTP 端口的检查对 worker 永远失败，`--wait` 把 unhealthy
当成失败。

**为什么难发现**：这个错误只在 CI 日志里出现一行 `is unhealthy`，本地 `pytest` 全绿；
而且**同样 `pull access denied for lottolab` 在历史成功 run 的日志里也出现过**
（那是 worker 没有 `build:` 段、compose 随后自行 build api 的正常噪音）—— 我先误判成
Docker Hub 限流，查了半天才定位到 `is unhealthy`。

**修法**：回滚镜像级 HEALTHCHECK；worker 也不配 healthcheck，并在两处写下原因：

- `pgrep` —— `python:3.12-slim` 不保证装了 procps，命令不存在会永远 unhealthy
- 读 `/proc/<pid>/cmdline` —— 依赖 Linux，本机（Windows）跑不了，等于写了一条自己测不了的检查
- 探测 api 的 HTTP 端点 —— worker 根本没有那个端口

worker 仍通过 `depends_on: api: condition: service_healthy` 保证启动顺序；worker 真挂了由
`scripts/check_container.py` 与后续 verify 步骤发现。要给它加健康检查，需先让它有
自己的可探测端点。

新增 `tests/test_container_health.py`（8 项）锁住这个回归：镜像级不得有 HEALTHCHECK 指令
（只查行首指令，注释里必须能解释「为什么不加」）、worker 不得有 healthcheck、
worker 仍等 api healthy、worker 复用 api 镜像不重复 build、api/db 保有各自检查、
CI 仍带 `--wait`+`--build`。两个变异测试确认有效（重新加回镜像级检查 → 挂 1；
给 worker 加 pgrep 检查 → 挂 1）。

### 修复 · 回归锁自己依赖了未声明的 PyYAML（2026-09-30）

`tests/test_container_health.py` 第一版 `import yaml` 解析 compose.yaml，但 `requirements.lock`
里没有 pyyaml，CI 只装 lock 文件 —— backend job 直接
`ModuleNotFoundError: No module named 'yaml'`。

**本地没发现的原因**：本机开发环境装了 pyyaml（我为了读 workflow 顺手装的），
所以 `pytest` 全绿。现有 28 个测试文件里没有任何一个 `import yaml`，只有我新加的这一个。

**修法**：改用标准库 `re` + 缩进切片读 compose.yaml。这些测试只需要「切出某个 service 的
块」和「有没有 healthcheck」，正则足够，也不用为一个测试引解析依赖 —— 「零多余依赖、
离线可跑」是这个项目的前提，不该为一个测试破掉。变异测试确认断言仍有效。

这条与上面的 HEALTHCHECK 回归是同一天、同一批 CI 反馈暴露的两个问题，性质相同：
**本地绿 ≠ CI 绿**，差别都在「本地环境比 CI 多/少了一些东西」。

### 文档 · 清理空的「未发布」章节（2026-09-30）

`## [未发布]` 此前是空标题（下一行直接是 1.1.0），本节填入上述内容。

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
