# 部署指南

[首页](../README.md) / 部署指南

LottoLab 支持 Vercel + PostgreSQL 云端部署，以及 Docker 自托管。以下步骤面向你自己的实例；新部署需要独立配置数据库。云端默认公开访问（无需管理员令牌），自托管可选择性配置令牌以限制写入。

## 选择部署方式

| 方式 | 服务组成 | 适用范围 |
| :--- | :--- | :--- |
| Vercel + Neon | Vercel 提供页面、API 与限时计算；Neon 保存数据库 | 个人使用、轻量实验，无需电脑持续开机 |
| Docker 自托管 | PostgreSQL、API、独立 worker，前端随 API 镜像提供 | 自有主机、较长任务与自主管理资源 |

Vercel Hobby 与 Neon Free 可用于符合其条款的个人部署。套餐容量、计算时长和免费政策可能变化，部署前查看 [Vercel 套餐](https://vercel.com/pricing)与 [Neon 套餐](https://neon.com/pricing)。免费服务不等于无限计算。

## Vercel + Neon

### 1. 准备源码与数据库

Fork 本仓库，并按 [本地安装指南](getting-started.md)完成 Python 依赖安装。下文命令中的 `python` 指项目虚拟环境中的解释器；Windows 可替换为 `./.venv/Scripts/python.exe`。

在 [Neon 控制台](https://console.neon.tech/)创建本项目专属的空 PostgreSQL 数据库，或通过 Vercel Marketplace 连接 Neon。应用函数使用 `iad1` 区域，数据库宜选择邻近区域。

复制数据库的 **pooled connection string**，保留 TLS 参数。连接格式为：

```text
postgresql://USER:PASSWORD@HOST-pooler.neon.tech/DB?sslmode=require
```

### 2. 生成私有配置并初始化数据

```bash
python scripts/bootstrap_env.py
python -m lottolab.cli migrate
python scripts/bootstrap_cloud.py
```

编辑新生成的 `.env.cloud.local`，将连接串填入 `LOTTOLAB_DATABASE_URL`。脚本已生成随机 `LOTTOLAB_ADMIN_TOKEN`；已有配置不会被覆盖。密钥只保存在本地私有文件与服务商环境变量中。

```bash
python scripts/bootstrap_cloud.py --check
python scripts/migrate_cloud.py
```

第一个命令仅验证语法；第二个对来源和目标做只读预检。来源由本地 `.env` 决定，可以是刚初始化的空库，也可以是你已有的 LottoLab 数据库。

确认源数据正确、没有运行任务、目标为专属空数据库后执行：

```bash
python scripts/migrate_cloud.py --apply
```

该命令创建目标表，复制开奖、导入记录、任务、冻结数据与原始快照，校验后提交。目标非空、含其他应用表、快照不完整或有活动任务时会停止。本地与云端数据库随后独立运行，不自动双向同步。

**首次迁移只对空目标执行。** 已运行实例的升级应使用对应的增量数据库迁移；构建脚本不会自动迁移生产数据库。

### 3. 配置 Vercel 项目

在 [Vercel](https://vercel.com/new)导入你的 GitHub 仓库，使用以下配置：

| 设置 | 值 |
| :--- | :--- |
| Root Directory | 仓库根目录 |
| Framework Preset | FastAPI |
| Python | 3.12，由 `.python-version` 指定 |
| Node.js | 24.x |
| Function Region | `iad1`，由 `vercel.json` 指定 |
| Build | 使用仓库的 `pyproject.toml` 配置，执行 `python scripts/build_vercel.py` |

构建脚本安装锁定的前端依赖，生成 `frontend/dist`。API 与静态页面部署到同一个项目；不要把根目录改为 `frontend`，否则会缺少 Python 服务。

将私有配置中的值添加到 Vercel 项目的 **Production** 环境：

| 环境变量 | 用途 |
| :--- | :--- |
| `LOTTOLAB_DATABASE_URL` | 必需，外部 PostgreSQL pooled 连接，启用 TLS |
| `LOTTOLAB_ADMIN_TOKEN` | 可选：不设则云端公开读写；设为至少 32 字符随机串则切为公开读、私有写（查询/推荐/验奖GET免令牌，同步/导入/回测等POST需令牌）。已设置但不足 32 字符会在启动时失败 |
| `LOTTOLAB_TRUSTED_PROXIES` | 可选：允许写入 `X-Forwarded-For` 的代理 IP/CIDR（逗号分隔）。回环与内网默认受信；生产建议加入 Cloudflare/Vercel 边缘地址，否则限流按直连对端 IP 计 |
| `LOTTOLAB_JOB_TIMEOUT_SECONDS` | 可选，默认 240，允许 1–240 |
| `LOTTOLAB_ALLOWED_HOSTS` | 可选，附加自定义域名，逗号分隔，不含协议、路径或端口 |
| `LOTTOLAB_ALLOWED_ORIGINS` | 可选，附加完整 HTTPS 来源，通常无需设置 |

Vercel 系统环境变量用于自动识别默认部署域名，应保留自动注入。环境变量修改后需要重新部署。数据库连接和令牌不应设置为 `VITE_*` 前端变量。

### 4. 验证并使用

部署完成后打开 Vercel 分配的 HTTPS 地址。先确认页面和 `/api/v1/health` 可用；云端默认公开，直接即可浏览数据（仅私有自托管才需输入管理员令牌）。

在自己的新实例中完成一次小规模同步或 CSV 导入，再运行一次模拟；刷新、重新鉴权后确认数据与实验结果仍可读取。若从本地迁入历史数据，同时核对彩种、期数与历史实验。

官方公开数据源可能限制部署地区的请求。同步失败时以导入报告为准，可使用 CSV；历史查询不依赖来源实时可用。

### 5. 配置预览与后续发布

Preview 使用独立数据库或数据库分支，以及独立管理员令牌。初始化预览数据库时，可将配置保存在 `.env.cloud.preview.local`，并显式指定目标：

```bash
python scripts/migrate_cloud.py --target-env .env.cloud.preview.local
python scripts/migrate_cloud.py --target-env .env.cloud.preview.local --apply
```

同样只对空目标执行。将这些值设置在 Vercel 的 Preview 环境，不要让预览指向 Production 数据库。

启用 Vercel Git 集成后，PR 创建预览部署，合并生产分支触发正式部署。发布前检查 [GitHub Actions](../.github/workflows/ci.yml)与预览核心流程；保留平台的 Deployment Protection。

如果希望使用 CLI，项目附带 `scripts/vercel_cli.py` 包装器，使用固定版本的 CLI 和本地私有认证目录：

```bash
python -c "from pathlib import Path; Path('.local/cloud-cli').mkdir(parents=True, exist_ok=True)"
pnpm --dir .local/cloud-cli add --save-exact --ignore-scripts vercel@59.16.0
python scripts/vercel_cli.py login
python scripts/vercel_cli.py link
python scripts/vercel_cli.py deploy --target preview
```

验证后使用 `python scripts/vercel_cli.py deploy --prod` 发布。第一次预览也应显式指定 `--target preview`。

## 运行限制

| 项目 | 本地 / Docker 默认 | Vercel |
| :--- | :--- | :--- |
| 计算 | 独立 worker 顺序执行 | 请求内执行，结果保存后返回 |
| 活动任务容量 | 排队与运行合计最多 8 项 | 最多 1 项 |
| 单任务时限 | 默认 600 秒，可配置 1–3600 秒 | 默认 240 秒，最多 240 秒 |
| CSV 大小 | 8 MiB | 4 MiB |
| CSV 行数 | 10,000 | 10,000 |
| 原始快照 | 文件系统 | 压缩存入 PostgreSQL |
| 数据访问 | 默认可读，写入规则由配置决定 | 未设令牌时公开读写；设令牌后公开读、私有写（验奖用GET免令牌） |
| 写请求限流 | POST /api/* 默认 120 次/分/IP（`LOTTOLAB_RATE_LIMIT_POSTS_PER_MINUTE`，0 关闭；XFF 仅受信代理生效）；重算 GET（recommend/verify/optimizations）默认 60 次/分（`LOTTOLAB_RATE_LIMIT_HEAVY_GETS_PER_MINUTE`） | 同左 |

云端无需常驻 worker。浏览器连接或函数运行被中断时，任务可能失败；重新鉴权后查看历史状态，不要假定断开的请求仍会完成。空闲数据库或函数唤醒可能增加首次响应时间。

## 自托管

先按 [Docker 安装说明](getting-started.md#docker-compose)启动。默认 Compose 只绑定本机端口，适合在前面接入 Caddy、Nginx 等 HTTPS 反向代理。

对外提供服务时，在 Compose override 或服务环境中设置实际域名与来源，并启用私人读取：

```dotenv
LOTTOLAB_ALLOW_LOCAL_WRITES=false
LOTTOLAB_REQUIRE_READ_AUTH=true
LOTTOLAB_ALLOWED_HOSTS=localhost,127.0.0.1,api,lab.example.com
LOTTOLAB_ALLOWED_ORIGINS=https://lab.example.com
```

`lab.example.com` 替换为实际域名。保留随机管理员令牌，持久化数据库和快照卷；不要公开 PostgreSQL 端口。上面 API 环境值须实际传入容器，仅写入 `.env` 不会覆盖 Compose 中已有的常量。

Cloudflare 可选用于 DNS：先在 Vercel 或反向代理中配置域名，再按平台提供的记录设置 DNS。Vercel 默认域名已提供 HTTPS，无自有域名也可使用。

## 备份与恢复

### 本地 SQLite

```bash
python scripts/backup_local.py
```

备份保存到新的 `.local/backups/` 子目录，包含数据库、文件快照和私有 `.env`。`manifest.json` 记录数据库完整性及数据文件校验值。备份含管理员令牌，应另存到私有位置。

恢复时先停止写入，在独立目录校验清单并打开数据库副本；将数据库连接和数据目录指向恢复位置，验证历史查询与实验后再切换。保留原数据库直到恢复确认完成。

### 云端 PostgreSQL

```bash
python scripts/backup_cloud.py
```

脚本默认读取 `.env.cloud.local`，以只读一致性快照导出到新的本地 SQLite，并在另一个新文件中恢复、逐表核对。它包含数据库中的压缩快照，不包含连接配置或管理员令牌；存在活动任务时会停止。

查看输出目录中的 `manifest.json`，确认 `restore_verification` 为 `PASS`，再将该目录保存到独立备份位置。

恢复云备份时，在隔离工作副本中将 `LOTTOLAB_DATABASE_URL` 指向备份 SQLite，并设置 `LOTTOLAB_SNAPSHOT_STORAGE=database`。验证后可通过 `migrate_cloud.py` 迁入**新的专属空 PostgreSQL**。连接配置与访问令牌需要单独恢复。

### Docker PostgreSQL

使用 PostgreSQL 的 `pg_dump` / `pg_restore` 管理数据库备份，并同时保留 `app_data` 卷中的原始快照。备份应覆盖同一静止写入时段；恢复先在独立数据库和数据卷中验证。

## 更新与回滚

更新前备份数据，阅读 [变更记录](../CHANGELOG.md)，在独立环境检查新版本。仅代码变化可重新构建部署；涉及数据库结构时，先确认迁移和兼容范围。

Vercel 可在控制台回滚到已验证的部署；Docker 可重新运行先前版本镜像。代码回滚不会自动恢复数据库，也不能替代数据库备份。
