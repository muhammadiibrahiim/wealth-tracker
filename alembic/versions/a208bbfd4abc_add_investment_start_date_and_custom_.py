"""add_investment_start_date_and_custom_leverage_repayment

Revision ID: a208bbfd4abc
Revises: bd0f86c9857a
Create Date: 2025-11-01 15:51:29.430635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a208bbfd4abc'
down_revision: Union[str, None] = 'bd0f86c9857a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add investment_start_date to investment table (default to 2025-01-01 for existing records)
    op.add_column('investment', sa.Column('investment_start_date', sa.Date(), nullable=False, server_default='2025-01-01'))
    
    # Add leverage_repayment_type to investment table
    op.add_column('investment', sa.Column('leverage_repayment_type', sa.String(length=50), nullable=False, server_default='equal_installments'))
    
    # Create leverage_repayment table for custom repayment schedules
    op.create_table(
        'leverage_repayment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('investment_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.DECIMAL(precision=15, scale=2), nullable=False),
        sa.Column('repayment_date', sa.Date(), nullable=False),
        sa.Column('repayment_month', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['investment_id'], ['investment.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_leverage_repayment_investment_id', 'leverage_repayment', ['investment_id'])


def downgrade() -> None:
    # Drop leverage_repayment table
    op.drop_index('idx_leverage_repayment_investment_id', table_name='leverage_repayment')
    op.drop_table('leverage_repayment')
    
    # Remove fields from investment table
    op.drop_column('investment', 'leverage_repayment_type')
    op.drop_column('investment', 'investment_start_date')
