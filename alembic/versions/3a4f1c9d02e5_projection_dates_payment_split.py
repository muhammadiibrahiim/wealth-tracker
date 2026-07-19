"""projection lines: order_date + vendor payment split

Revision ID: 3a4f1c9d02e5
Revises: 1e12d756ffb1
Create Date: 2026-07-15 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3a4f1c9d02e5"
down_revision: Union[str, None] = "1e12d756ffb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# column name -> DDL used when adding it
_NEW_COLUMNS = [
    ("order_date", sa.Column("order_date", sa.Date(), nullable=True)),
    ("pct_advance", sa.Column("pct_advance", sa.DECIMAL(6, 2), nullable=False, server_default="0")),
    ("pct_on_delivery", sa.Column("pct_on_delivery", sa.DECIMAL(6, 2), nullable=False, server_default="100")),
    ("pct_credit", sa.Column("pct_credit", sa.DECIMAL(6, 2), nullable=False, server_default="0")),
    ("credit_days", sa.Column("credit_days", sa.Integer(), nullable=False, server_default="30")),
]


def _existing_columns(conn) -> set:
    insp = sa.inspect(conn)
    if "projection_lines" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("projection_lines")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _existing_columns(conn)
    if not have:  # table not created yet (fresh install builds it via create_all)
        return
    for name, column in _NEW_COLUMNS:
        if name not in have:
            op.add_column("projection_lines", column)


def downgrade() -> None:
    conn = op.get_bind()
    have = _existing_columns(conn)
    for name, _ in reversed(_NEW_COLUMNS):
        if name in have:
            op.drop_column("projection_lines", name)
