"""customer credits — make source_account_id optional (same-account reallocation)

Revision ID: d1a5e7c93f42
Revises: c7d84f21a9b6
Create Date: 2026-08-12 23:30:00.000000

The table shipped a few hours before this migration and has never held real
data (confirmed empty), so this recreates it rather than doing a cautious
add-column/backfill/drop dance — no rows to preserve.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1a5e7c93f42"
down_revision: Union[str, None] = "c7d84f21a9b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "trade_customer_credits" in _tables(conn):
        op.drop_table("trade_customer_credits")
    op.create_table(
        "trade_customer_credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(),
                  sa.ForeignKey("trade_parties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_account_id", sa.Integer(),
                  sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("amount", sa.DECIMAL(precision=15, scale=2), nullable=False),
        sa.Column("remaining_amount", sa.DECIMAL(precision=15, scale=2), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_customer_credit_customer", "trade_customer_credits", ["customer_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if "trade_customer_credits" in _tables(conn):
        op.drop_table("trade_customer_credits")
