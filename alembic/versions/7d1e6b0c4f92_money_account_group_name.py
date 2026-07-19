"""money_accounts: group_name for Money-Manager-exact grouping

Revision ID: 7d1e6b0c4f92
Revises: 6c9d4e21f8a3
Create Date: 2026-07-17 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d1e6b0c4f92"
down_revision: Union[str, None] = "6c9d4e21f8a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "money_accounts" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("money_accounts")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if have and "group_name" not in have:
        op.add_column("money_accounts", sa.Column("group_name", sa.String(length=80), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if "group_name" in _cols(conn):
        op.drop_column("money_accounts", "group_name")
