"""add_revenue_fields_to_investment

Revision ID: 38fb5615197a
Revises: 27a3ed65712c
Create Date: 2025-11-01 14:55:38.015207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38fb5615197a'
down_revision: Union[str, None] = '27a3ed65712c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add revenue fields for business-type investments
    op.add_column('investment', sa.Column('has_revenue', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('investment', sa.Column('revenue_amount', sa.DECIMAL(precision=15, scale=2), nullable=False, server_default='0.00'))
    op.add_column('investment', sa.Column('revenue_installment_months', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove revenue fields
    op.drop_column('investment', 'revenue_installment_months')
    op.drop_column('investment', 'revenue_amount')
    op.drop_column('investment', 'has_revenue')
