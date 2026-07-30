"""partner.is_owner (owner's own capital account flag)

Revision ID: b8d5f3a10c47
Revises: a7c4e21b9d30
Create Date: 2026-07-30 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d5f3a10c47"
down_revision: Union[str, None] = "a7c4e21b9d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "partners" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("partners")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if have and "is_owner" not in have:
        op.add_column("partners", sa.Column("is_owner", sa.Boolean(), nullable=False,
                                            server_default=sa.false()))


def downgrade() -> None:
    conn = op.get_bind()
    if "is_owner" in _cols(conn):
        op.drop_column("partners", "is_owner")
