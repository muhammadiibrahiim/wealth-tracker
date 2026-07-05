"""Add gain_in_income_value column to investment table

Revision ID: c8c444d3a77a
Revises: 702d7f7b6efb
Create Date: 2025-11-01 12:56:04.711031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8c444d3a77a'
down_revision: Union[str, None] = '702d7f7b6efb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('investment', sa.Column('gain_in_income_value', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0.00'))


def downgrade() -> None:
    op.drop_column('investment', 'gain_in_income_value')
