"""trade purchases (per-line cost entries) + cost_pending flag

Revision ID: 8e2a5c14bd77
Revises: 7d1e6b0c4f92
Create Date: 2026-07-17 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "8e2a5c14bd77"
down_revision: Union[str, None] = "7d1e6b0c4f92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def _cols(conn, table) -> set:
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if "cost_pending" not in _cols(conn, "trade_lines"):
        op.add_column("trade_lines", sa.Column(
            "cost_pending", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    if "trade_purchases" not in _tables(conn):
        op.create_table(
            "trade_purchases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("trade_id", sa.Integer(), nullable=False),
            sa.Column("line_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.DECIMAL(15, 3), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.DECIMAL(15, 2), nullable=False, server_default="0"),
            sa.Column("purchased_on", sa.Date(), nullable=False),
            sa.Column("vendor_invoice_path", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
            sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["line_id"], ["trade_lines.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_trade_purchase_trade", "trade_purchases", ["trade_id"], unique=False)
        op.create_index("idx_trade_purchase_line", "trade_purchases", ["line_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if "trade_purchases" in _tables(conn):
        op.drop_table("trade_purchases")
    if "cost_pending" in _cols(conn, "trade_lines"):
        op.drop_column("trade_lines", "cost_pending")
