"""Add investment_type column to investment table

Revision ID: b41d17aab32a
Revises: c8c444d3a77a
Create Date: 2025-11-01 13:01:32.485543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41d17aab32a'
down_revision: Union[str, None] = 'c8c444d3a77a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('investment', sa.Column('investment_type', sa.String(), nullable=False, server_default='asset'))


def downgrade() -> None:
    op.drop_column('investment', 'investment_type')
