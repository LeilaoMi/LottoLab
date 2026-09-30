"""ingestion_runs 增加 sources_cross_checked：如实记录「这批到底有没有经过多源比对」。

Revision ID: x2srcval01
Revises: c41predlog01
Create Date: 2026-09-30

为什么加这一列

README 写着「多源交叉校验，不一致的期号拒绝入库」，但生产写入路径
（collector/daily_sync.py）是单源 append：硬编码 source="17500"，从不 import
collect_core.ingest。带多源语义指纹比对与 rejected[issue] 的逻辑只在
collector/shadow_parallel.py，而影子的 DIVERGE → sys.exit(1) 是告警不是拦截。

于是「单源入库」与「多源校验后入库」在 ingestion_runs 里长得一模一样：
conflicts 恒为 0，读表的人无法区分「比对过且一致」和「压根没比对」。
这与 v0.15.2 之前「单源却记 consistent=true」的假绿是同一类问题 ——
让指标看起来像被检验过，而检验从未发生。

取值
  True  本批号码经过 >=2 个源的逐期语义比对（走 collect_core.ingest 路径）
  False 单源直接入库，未经第二源比对

已有行的回填口径：全部置 False。历史行都是单源 daily_sync 写的，
按 True 回填等于凭空造出一批从未发生过的校验记录。
"""

import sqlalchemy as sa
from alembic import op

revision = "x2srcval01"
down_revision = "c41predlog01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default=false：老行与新写的单源行都落到 False（默认「未校验」而不是「已校验」）
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "sources_cross_checked",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "sources_cross_checked")
