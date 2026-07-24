"""projection line: dye_active toggle (exclude one-time dye/block from KPIs)

Revision ID: c3e6a9d2f440
Revises: b2d5f8a1c331
Create Date: 2026-07-25 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3e6a9d2f440"
down_revision: Union[str, None] = "b2d5f8a1c331"
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
    if "dye_active" not in have:
        op.add_column("projection_lines", sa.Column(
            "dye_active", sa.Boolean(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    conn = op.get_bind()
    if "dye_active" in _cols(conn):
        op.drop_column("projection_lines", "dye_active")
