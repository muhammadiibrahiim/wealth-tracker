"""add_leverage_fields_to_investment

Revision ID: 27a3ed65712c
Revises: 99d56ea97b64
Create Date: 2025-11-01 14:38:01.378472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27a3ed65712c'
down_revision: Union[str, None] = '99d56ea97b64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add leverage fields to investment table
    op.add_column('investment', sa.Column('is_leveraged', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('investment', sa.Column('leverage_amount', sa.DECIMAL(15, 2), nullable=False, server_default='0.00'))
    op.add_column('investment', sa.Column('leverage_repayment_month', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove leverage fields from investment table
    op.drop_column('investment', 'leverage_repayment_month')
    op.drop_column('investment', 'leverage_amount')
    op.drop_column('investment', 'is_leveraged')
