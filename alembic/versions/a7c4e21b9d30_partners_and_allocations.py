"""partners + partner_allocations (equity partners, monthly profit split)

Revision ID: a7c4e21b9d30
Revises: f6b2d0e94a27
Create Date: 2026-07-30 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c4e21b9d30"
down_revision: Union[str, None] = "f6b2d0e94a27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    have = _tables(conn)
    if "partners" not in have:
        op.create_table(
            "partners",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False, index=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("account_id", sa.Integer(),
                      sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pct", sa.DECIMAL(7, 4), nullable=False, server_default="0"),
            sa.Column("joined_on", sa.Date(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("idx_partner_user", "partners", ["user_id"])
    if "partner_allocations" not in have:
        op.create_table(
            "partner_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False, index=True),
            sa.Column("period", sa.Date(), nullable=False),
            sa.Column("profit", sa.DECIMAL(15, 2), nullable=False, server_default="0"),
            sa.Column("journal_entry_id", sa.Integer(),
                      sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("idx_partner_alloc_period", "partner_allocations",
                        ["user_id", "period"], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    have = _tables(conn)
    if "partner_allocations" in have:
        op.drop_table("partner_allocations")
    if "partners" in have:
        op.drop_table("partners")
