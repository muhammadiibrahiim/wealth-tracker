"""trade split payment terms (advance / delivery / credit %)

Revision ID: 9f3b7c22e18d
Revises: 8e2a5c14bd77
Create Date: 2026-07-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f3b7c22e18d"
down_revision: Union[str, None] = "8e2a5c14bd77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = [
    ("cust_advance_pct", "0"),
    ("cust_delivery_pct", "0"),
    ("cust_credit_pct", "100"),
    ("vend_advance_pct", "0"),
    ("vend_delivery_pct", "0"),
    ("vend_credit_pct", "100"),
]


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
    for name, default in _COLS:
        if name not in have:
            op.add_column("trades", sa.Column(
                name, sa.DECIMAL(6, 2), nullable=False, server_default=default))


def downgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    for name, _ in reversed(_COLS):
        if name in have:
            op.drop_column("trades", name)
