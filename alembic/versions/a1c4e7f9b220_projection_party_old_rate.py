"""projection line: party old buy rate (reference column)

Revision ID: a1c4e7f9b220
Revises: 9f3b7c22e18d
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e7f9b220"
down_revision: Union[str, None] = "9f3b7c22e18d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "projection_lines" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("projection_lines")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if not have:
        return
    if "party_old_rate" not in have:
        op.add_column("projection_lines", sa.Column(
            "party_old_rate", sa.DECIMAL(15, 4), nullable=False, server_default="0"))


def downgrade() -> None:
    conn = op.get_bind()
    if "party_old_rate" in _cols(conn):
        op.drop_column("projection_lines", "party_old_rate")
