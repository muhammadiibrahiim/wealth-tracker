"""trade payment: proof_path (uploaded payment screenshot / receipt)

Revision ID: d4f7b1a8e552
Revises: c3e6a9d2f440
Create Date: 2026-07-27 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f7b1a8e552"
down_revision: Union[str, None] = "c3e6a9d2f440"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "trade_payments" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("trade_payments")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if not have:
        return
    if "proof_path" not in have:
        op.add_column("trade_payments", sa.Column(
            "proof_path", sa.String(length=300), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if "proof_path" in _cols(conn):
        op.drop_column("trade_payments", "proof_path")
