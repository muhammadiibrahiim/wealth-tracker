"""projection line: group_name (Dabbi / Stickers grouping)

Revision ID: b2d5f8a1c331
Revises: a1c4e7f9b220
Create Date: 2026-07-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d5f8a1c331"
down_revision: Union[str, None] = "a1c4e7f9b220"
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
    if "group_name" not in have:
        op.add_column("projection_lines", sa.Column(
            "group_name", sa.String(80), nullable=False, server_default="Dabbi"))


def downgrade() -> None:
    conn = op.get_bind()
    if "group_name" in _cols(conn):
        op.drop_column("projection_lines", "group_name")
