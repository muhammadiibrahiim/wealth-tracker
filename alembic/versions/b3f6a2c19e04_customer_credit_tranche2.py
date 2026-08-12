"""trades: second customer credit tranche (cust_credit2_pct, customer_terms2_days)

Revision ID: b3f6a2c19e04
Revises: 98489b14c7ac
Create Date: 2026-08-12 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f6a2c19e04"
down_revision: Union[str, None] = "98489b14c7ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "trades" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("trades")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if not have:
        return
    if "cust_credit2_pct" not in have:
        op.add_column("trades", sa.Column(
            "cust_credit2_pct", sa.DECIMAL(precision=6, scale=2),
            nullable=False, server_default="0"))
    if "customer_terms2_days" not in have:
        op.add_column("trades", sa.Column(
            "customer_terms2_days", sa.Integer(),
            nullable=False, server_default="0"))


def downgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if "customer_terms2_days" in have:
        op.drop_column("trades", "customer_terms2_days")
    if "cust_credit2_pct" in have:
        op.drop_column("trades", "cust_credit2_pct")
