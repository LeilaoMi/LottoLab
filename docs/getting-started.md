# 安装与启动

[首页](../README.md) / 安装与启动

LottoLab 可通过 Docker 运行完整服务，也可直接安装到本机。两种方式使用独立的数据存储；切换方式不会自动搬迁数据。

## 选择运行方式

| 方式 | 前提 | 默认入口 |
| :--- | :--- | :--- |
| Docker Compose | Git、Python 3.12、Docker、Compose v2 | [127.0.0.1:18080](http://127.0.0.1:18080) |
| 本机安装 | Git、Python 3.12、Node.js 24、pnpm 11.19.0 | [127.0.0.1:8000](http://127.0.0.1:8000) |
| 云端部署 | Vercel 与 PostgreSQL 服务账号 | 见 [部署指南](deployment.md) |

先下载项目，并在仓库根目录执行后续命令：

```bash
git clone https://github.com/LeilaoMi/lottery-design.git
cd lottery-design
```

## Docker Compose

```bash
python scripts/bootstrap_env.py
docker compose up -d --build --wait
```

配置脚本会生成随机数据库密码和管理员令牌，写入本地 `.env`。已有配置会完整保留。Compose 构建前端并启动 PostgreSQL 17、API 和计算 worker，无需在主机安装 Node.js。

打开 [http://127.0.0.1:18080](http://127.0.0.1:18080)。查询默认可用；同步、导入和计算需要在“管理权限”中输入 `.env` 中的 `LOTTOLAB_ADMIN_TOKEN`。

```bash
docker compose ps
docker compose logs --tail 100 api worker
docker compose down
```

`down` 保留数据库和原始快照的命名卷。再次运行 `docker compose up -d --wait` 即可启动；日常停止不要附加 `--volumes`。

默认端口只绑定本机：界面为 18080，PostgreSQL 为 55432。对外服务请按 [自托管说明](deployment.md#自托管)配置 HTTPS 与鉴权。

## Windows 本机安装

安装 Python 3.12 和 Node.js 24。如果尚未安装对应 pnpm，先执行：

```powershell
npm install --global pnpm@11.19.0
```

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock
./.venv/Scripts/python.exe -m pip install --no-deps -e .
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
./.venv/Scripts/python.exe scripts/bootstrap_env.py
./Start-LottoLab.cmd
```

启动器检查数据库迁移，启动 API 和 worker，并打开浏览器。后续可直接双击 `Start-LottoLab.cmd`。保留启动窗口，按 `Ctrl+C` 停止服务。

## Linux / macOS 本机安装

安装 Python 3.12、Node.js 24 与 pnpm 11.19.0 后执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.venv/bin/python scripts/bootstrap_env.py
.venv/bin/python scripts/start_local.py
```

## 本地配置与启动选项

默认数据库为 `.local/lottolab.db`，原始快照在 `.local/raw/`。配置位于 `.env`，可用变量见 [配置示例](../.env.example)。配置、数据库和日志均不应提交到 Git。

Windows 启动选项：

```powershell
./Start-LottoLab.cmd --check
./Start-LottoLab.cmd --port 8001
./Start-LottoLab.cmd --no-browser
```

Linux / macOS 将启动器替换为 `.venv/bin/python scripts/start_local.py`，使用相同参数。`--check` 检查启动所需文件，不代表已经验证数据库连接；运行日志位于 `.local/api.log` 与 `.local/worker.log`。

需要原生进程连接 Compose 中的 PostgreSQL 时，可在**首次生成配置**时使用 `python scripts/bootstrap_env.py --postgres`。已有 `.env` 不会被改写，启动器管理的本地 PostgreSQL 端口为 55432。

## 准备第一份数据

全新安装不含历史数据库。打开页面后选择双色球或大乐透，再使用“同步数据”或“导入 CSV”。导入完成后，检查实际日期范围、来源和质量报告，再进入统计或实验页面。

也可使用命令行。以下 `python` 指虚拟环境中的解释器；Windows 未激活环境时替换为 `./.venv/Scripts/python.exe`。

```bash
python -m lottolab.cli migrate
python -m lottolab.cli sync --lottery ssq --count 1000
python -m lottolab.cli sync --lottery dlt --count 300
```

离线体验可生成**合成演示数据**：

```bash
python -m lottolab.cli demo --lottery ssq --count 600 --seed 2026
```

随后在页面切换到“演示数据”。演示期号以 `SIM-` 开头，不代表真实开奖结果，也不计算历史收益。

## 常见启动问题

| 现象 | 处理 |
| :--- | :--- |
| 提示前端未构建 | 执行 `pnpm --dir frontend build` |
| 端口被占用 | 使用 `--port 8001`，或检查已有服务 |
| 页面显示 worker 离线 | 检查 `.local/worker.log`；使用启动器同时启动 API 与 worker |
| Docker 无法连接 | 先启动 Docker 服务，或改用本机 SQLite 安装 |
| 同步失败 | 查看导入报告；公开来源恢复前可使用 [CSV 导入](user-guide.md#csv-格式) |
| 更新配置后无变化 | 停止并重新启动对应服务；数据库不会随配置切换自动搬迁 |

下一步：[使用指南](user-guide.md) · [研究方法](methodology.md)
