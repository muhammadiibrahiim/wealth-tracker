"""item vendor quotes — vendor's quoted buy rate per item, reference only

Revision ID: 98489b14c7ac
Revises: a3f7e29c8d61
Create Date: 2026-08-11 18:54:24.482403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "98489b14c7ac"
down_revision: Union[str, None] = "a3f7e29c8d61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "trade_item_vendor_quotes" not in _tables(conn):
        op.create_table(
            "trade_item_vendor_quotes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("trade_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("trade_parties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("quoted_rate", sa.DECIMAL(precision=15, scale=4), nullable=False),
            sa.Column("quoted_date", sa.Date(), nullable=False),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("idx_item_vendor_quote_item", "trade_item_vendor_quotes", ["item_id"])
        op.create_index("idx_item_vendor_quote_vendor", "trade_item_vendor_quotes", ["vendor_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if "trade_item_vendor_quotes" in _tables(conn):
        op.drop_table("trade_item_vendor_quotes")
