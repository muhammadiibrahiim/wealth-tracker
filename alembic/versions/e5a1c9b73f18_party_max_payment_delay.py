"""party: max_payment_delay_days (vendor payment stretch limit)

Revision ID: e5a1c9b73f18
Revises: d4f7b1a8e552
Create Date: 2026-07-28 03:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5a1c9b73f18"
down_revision: Union[str, None] = "d4f7b1a8e552"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "trade_parties" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("trade_parties")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if not have:
        return
    if "max_payment_delay_days" not in have:
        op.add_column("trade_parties", sa.Column(
            "max_payment_delay_days", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    conn = op.get_bind()
    if "max_payment_delay_days" in _cols(conn):
        op.drop_column("trade_parties", "max_payment_delay_days")
