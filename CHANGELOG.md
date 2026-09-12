# 变更记录

记录已发布版本中影响使用和部署的变化。源码与固定版本下载见 [Releases](https://github.com/LeilaoMi/lottery-design/releases)。

## [1.0.0](https://github.com/LeilaoMi/lottery-design/releases/tag/v1.0.0) · 2026-09-13

首个稳定版本，提供完整的 SSQ / DLT 数据研究流程。

- 支持公开数据同步、CSV 导入导出、原始快照、质量报告和可追溯修订。
- 提供历史统计、无放回零模型、Monte Carlo 随机性检验和多重比较校正。
- 提供均匀随机、历史频率、逻辑回归、梯度提升树的时间回测，保存冻结数据和逐期结果。
- 提供随机模拟、条件收益计算、贪心组合覆盖和覆盖率区间。
- 提供八个中文页面、深色主题、移动端布局、实验状态和结果历史。
- 支持本地 SQLite、Docker / PostgreSQL，以及 Vercel + Neon 云端部署。
- 提供数据库迁移、本地备份与只读云备份；云备份包含独立恢复校验。

SSQ 收益计算依赖完整的历史奖级资料，DLT ROI 暂不提供。计算限制与方法边界见 [部署指南](docs/deployment.md) 和 [研究方法](docs/methodology.md)。
