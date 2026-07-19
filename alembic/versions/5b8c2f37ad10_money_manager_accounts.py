"""personal Money Manager accounts + transactions

Revision ID: 5b8c2f37ad10
Revises: 3a4f1c9d02e5
Create Date: 2026-07-15 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "5b8c2f37ad10"
down_revision: Union[str, None] = "3a4f1c9d02e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    have = _tables(conn)

    if "money_accounts" not in have:
        op.create_table(
            "money_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
            sa.Column("type", sa.String(length=20), nullable=False, server_default="other"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_money_account_user", "money_accounts", ["user_id"], unique=False)
        op.create_index("ix_money_accounts_user_id", "money_accounts", ["user_id"], unique=False)
        op.create_index("ix_money_accounts_name", "money_accounts", ["name"], unique=False)

    if "money_txns" not in have:
        op.create_table(
            "money_txns",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("counter_account_id", sa.Integer(), nullable=True),
            sa.Column("category", sa.String(length=200), nullable=True),
            sa.Column("subcategory", sa.String(length=200), nullable=True),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("amount", sa.DECIMAL(precision=16, scale=2), nullable=False, server_default="0"),
            sa.Column("direction", sa.String(length=4), nullable=False),
            sa.Column("kind", sa.String(length=12), nullable=False, server_default="transfer"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="PKR"),
            sa.Column("source_hash", sa.String(length=64), nullable=False),
            sa.Column("import_batch", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["money_accounts.id"]),
            sa.ForeignKeyConstraint(["counter_account_id"], ["money_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_money_txn_user_hash", "money_txns", ["user_id", "source_hash"], unique=False)
        op.create_index("idx_money_txn_account", "money_txns", ["account_id"], unique=False)
        op.create_index("ix_money_txns_user_id", "money_txns", ["user_id"], unique=False)
        op.create_index("ix_money_txns_occurred_at", "money_txns", ["occurred_at"], unique=False)
        op.create_index("ix_money_txns_account_id", "money_txns", ["account_id"], unique=False)
        op.create_index("ix_money_txns_source_hash", "money_txns", ["source_hash"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    have = _tables(conn)
    if "money_txns" in have:
        op.drop_table("money_txns")
    if "money_accounts" in have:
        op.drop_table("money_accounts")
