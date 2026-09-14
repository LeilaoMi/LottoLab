"""family-aware number constraint (POOL/DIGIT)

Revision ID: b30fami1y01
Revises: 764ec2a315be
Create Date: 2026-09-14

把 draws.ck_draw_numbers 从"仅 ssq/dlt 池型"换成 family-aware：
POOL 保持升序去重、DIGIT 逐位有序可重含 0。由 lottolab.db.number_constraint() 派生，
与模型单一来源，避免手写漂移。现有 ssq/dlt 行逐条等价，升级零风险。
"""

from alembic import op
from lottolab.db import number_constraint

revision = "b30fami1y01"
down_revision = "764ec2a315be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("draws") as batch_op:
        batch_op.drop_constraint("ck_draw_numbers", type_="check")
        batch_op.create_check_constraint("ck_draw_numbers", number_constraint())


def downgrade() -> None:
    from lottolab.domain import RULES

    def pool_clause(r) -> str:
        terms = [f"lottery = '{r.code}'"]
        for field, count, maximum in (
            ("main_numbers", r.main_count, r.main_max),
            ("special_numbers", r.special_count, r.special_max),
        ):
            terms.append(f"coalesce(json_array_length({field}), -1) = {count}")
            for i in range(count):
                terms.append(f"CAST({field} ->> {i} AS INTEGER) BETWEEN 1 AND {maximum}")
                if i:
                    terms.append(f"CAST({field} ->> {i - 1} AS INTEGER) < CAST({field} ->> {i} AS INTEGER)")
        return "(" + " AND ".join(terms) + ")"

    legacy = " OR ".join(pool_clause(RULES[k]) for k in ("ssq", "dlt"))
    with op.batch_alter_table("draws") as batch_op:
        batch_op.drop_constraint("ck_draw_numbers", type_="check")
        batch_op.create_check_constraint("ck_draw_numbers", legacy)
