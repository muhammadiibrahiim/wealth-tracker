"""journal entry: proof_path (uploaded payment screenshot / receipt for standalone vouchers)

Revision ID: f2a8c6d91b53
Revises: b8d5f3a10c47
Create Date: 2026-08-05 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a8c6d91b53"
down_revision: Union[str, None] = "b8d5f3a10c47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(conn) -> set:
    insp = sa.inspect(conn)
    if "journal_entries" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("journal_entries")}


def upgrade() -> None:
    conn = op.get_bind()
    have = _cols(conn)
    if not have:
        return
    if "proof_path" not in have:
        op.add_column("journal_entries", sa.Column(
            "proof_path", sa.String(length=300), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if "proof_path" in _cols(conn):
        op.drop_column("journal_entries", "proof_path")
