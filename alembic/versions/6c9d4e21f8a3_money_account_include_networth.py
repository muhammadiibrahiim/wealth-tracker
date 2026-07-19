"""money_accounts: include_in_networth flag

Revision ID: 6c9d4e21f8a3
Revises: 5b8c2f37ad10
Create Date: 2026-07-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6c9d4e21f8a3"
down_revision: Union[str, None] = "5b8c2f37ad10"
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
    if have and "include_in_networth" not in have:
        op.add_column(
            "money_accounts",
            sa.Column("include_in_networth", sa.Boolean(), nullable=False,
                      server_default=sa.text("1")),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "include_in_networth" in _cols(conn):
        op.drop_column("money_accounts", "include_in_networth")
