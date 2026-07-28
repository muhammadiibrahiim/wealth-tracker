"""trade: expected_delivery_date (owner-set arrival for on-order goods)

Revision ID: f6b2d0e94a27
Revises: e5a1c9b73f18
Create Date: 2026-07-28 03:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b2d0e94a27"
down_revision: Union[str, None] = "e5a1c9b73f18"
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
    if "expected_delivery_date" not in have:
        op.add_column("trades", sa.Column("expected_delivery_date", sa.Date(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if "expected_delivery_date" in _cols(conn):
        op.drop_column("trades", "expected_delivery_date")
