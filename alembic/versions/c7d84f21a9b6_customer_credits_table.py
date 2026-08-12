"""customer credits — unapplied credit balance reserved for a customer

Revision ID: c7d84f21a9b6
Revises: b3f6a2c19e04
Create Date: 2026-08-12 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d84f21a9b6"
down_revision: Union[str, None] = "b3f6a2c19e04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "trade_customer_credits" not in _tables(conn):
        op.create_table(
            "trade_customer_credits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(),
                      sa.ForeignKey("trade_parties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_account_id", sa.Integer(),
                      sa.ForeignKey("accounts.id"), nullable=False),
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
