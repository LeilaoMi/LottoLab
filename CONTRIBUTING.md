# 贡献指南

感谢帮助改进 LottoLab。适合贡献的内容包括数据来源适配、错误修复、可复现的统计方法、无障碍与界面改进，以及更清晰的使用文档。

提交问题时请说明版本、运行方式、复现步骤、预期与实际结果。日志和样本中移除令牌、连接串与个人信息。提交 PR 时写明具体行为变化和实际验证结果。

## 开发环境

先完成 [本地安装](docs/getting-started.md)。Python 使用 3.12，前端使用 Node.js 24 与 pnpm 11.19.0；依赖以仓库锁文件为准。

后端开发可在激活虚拟环境后，分别在两个终端运行：

```bash
python -m lottolab.cli migrate
python -m lottolab.cli serve
```

```bash
python -m lottolab.worker
```

第三个终端启动前端：

```bash
pnpm --dir frontend dev
```

访问 [http://127.0.0.1:5173](http://127.0.0.1:5173)。API 默认监听本机 8000 端口，Vite 代理 `/api` 请求。`.env.example` 已包含开发来源；API 与 worker 需使用相同数据库和数据目录。完整启动器会收紧来源到自身端口，前端开发时使用上述独立进程。

## 源码结构

| 目录 / 文件 | 职责 |
| :--- | :--- |
| `backend/lottolab/` | API、数据校验与导入、统计、特征、回测、覆盖和任务执行 |
| `frontend/src/` | React 页面、组件、API 客户端和样式 |
| `tests/` | 数据契约、数学方法、时间边界、任务与数据库回归 |
| `frontend/e2e/` | 本地 worker 和云端请求模式的浏览器流程 |
| `migrations/` | Alembic 数据库迁移 |
| `scripts/` | 启动、配置、备份、部署和环境验证工具 |
| `docker/`、`compose.yaml` | 容器构建与服务编排 |
| `docs/` | 面向使用者与部署者的文档 |

数据库和临时资料位于被忽略的 `.local/`。开发笔记、任务流水、个人配置、原始设计附件和测试生成物不加入公开源码树。

## 验证改动

以下命令与 [CI 工作流](.github/workflows/ci.yml)一致。`python` 指虚拟环境解释器；Windows 也可使用 `./.venv/Scripts/python.exe`。

```bash
python -m pip check
python -m ruff check backend tests scripts migrations app.py
python -m ruff format --check backend tests scripts migrations app.py
python -m mypy backend
python -m pytest -q
pnpm --dir frontend exec prettier --check src e2e playwright.config.ts playwright.cloud.config.ts vite.config.ts
pnpm --dir frontend build
pnpm --dir frontend exec playwright test
pnpm --dir frontend exec playwright test --config playwright.cloud.config.ts
```

浏览器测试使用独立 SQLite 文件与 8011 / 8012 端口。Windows 优先使用已安装的 Edge；其他环境可先执行 `pnpm --dir frontend exec playwright install --with-deps chromium`。这里的云端测试在本地模拟请求模式，不连接你的线上实例。

真实 PostgreSQL 检查需要 `LOTTOLAB_TEST_DATABASE_URL` 指向专用测试库；测试只创建并清理自身临时 schema。未配置时相应检查会跳过。CI 配有临时 PostgreSQL 17，并验证 Docker 重建后保留数据与快照。

按影响范围运行检查，记录通过、失败或未执行的原因。文档改动应核对命令、链接和真实渲染；无需为纯文字改动编写无意义的单元测试。

## 数据与研究贡献

统计或模型改动需给出假设、指标定义、随机基线、适用条件与有意义的验证。预测第 `t` 期只能使用此前信息；拟合、调参与校准不得使用测试结果。

重点验证未来数据扰动不改变过去预测、无放回概率模型正确、实验比较窗口和预算一致。不得以删掉断言或只展示最好一次结果来宣称改进。

演示数据必须标记为 synthetic。公开数据适配保留来源与原始快照，非法记录应可解释，真实缺期不得插值。方法限制同时更新 [研究方法](docs/methodology.md)。

## 提交与发布

PR 保持聚焦，说明解决的问题、结果与验证。涉及数据库结构时提供增量迁移，并说明对已有数据和回滚的影响。依赖变化同步更新相应锁文件。

版本发布前检查独立预览和 CI；密钥不进入代码、构建产物或 PR 描述。生产部署与备份流程见 [部署指南](docs/deployment.md)。
