"""add projection_lines table

Revision ID: 1e12d756ffb1
Revises: 2e7193a10abf
Create Date: 2026-07-15 16:51:33.276785

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1e12d756ffb1'
down_revision: Union[str, None] = '2e7193a10abf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: this app also builds tables via SQLModel.metadata.create_all on
    # startup, so projection_lines may already exist depending on ordering. Only
    # create it if it isn't there yet.
    conn = op.get_bind()
    if "projection_lines" in sa.inspect(conn).get_table_names():
        return
    op.create_table(
        "projection_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("quantity", sa.DECIMAL(precision=15, scale=3), nullable=False, server_default="0"),
        sa.Column("purchase_rate", sa.DECIMAL(precision=15, scale=4), nullable=False, server_default="0"),
        sa.Column("sale_rate", sa.DECIMAL(precision=15, scale=4), nullable=False, server_default="0"),
        sa.Column("dye_block_cost", sa.DECIMAL(precision=15, scale=2), nullable=False, server_default="0"),
        sa.Column("bilty", sa.DECIMAL(precision=15, scale=2), nullable=False, server_default="0"),
        sa.Column("lead_days", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("collection_lag_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("pay_on_delivery", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_projection_line_user", "projection_lines", ["user_id"], unique=False)
    op.create_index("ix_projection_lines_user_id", "projection_lines", ["user_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if "projection_lines" not in sa.inspect(conn).get_table_names():
        return
    op.drop_table("projection_lines")
