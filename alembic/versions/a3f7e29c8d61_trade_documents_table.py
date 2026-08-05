"""trade documents — standalone document library (paste/name/search)

Revision ID: a3f7e29c8d61
Revises: f2a8c6d91b53
Create Date: 2026-08-06 09:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f7e29c8d61"
down_revision: Union[str, None] = "f2a8c6d91b53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "trade_documents" not in _tables(conn):
        op.create_table(
            "trade_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=120), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        )
        op.create_index("idx_trade_document_user", "trade_documents", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if "trade_documents" in _tables(conn):
        op.drop_table("trade_documents")
