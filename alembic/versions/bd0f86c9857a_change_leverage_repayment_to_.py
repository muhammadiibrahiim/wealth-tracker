"""change_leverage_repayment_to_installments

Revision ID: bd0f86c9857a
Revises: 38fb5615197a
Create Date: 2025-11-01 15:12:28.689033

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd0f86c9857a'
down_revision: Union[str, None] = '38fb5615197a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename leverage_repayment_month to leverage_repayment_months
    with op.batch_alter_table('investment') as batch_op:
        batch_op.alter_column('leverage_repayment_month', 
                             new_column_name='leverage_repayment_months',
                             existing_type=sa.Integer(),
                             nullable=True)
    
    # Add leverage_monthly_repayment field
    op.add_column('investment', sa.Column('leverage_monthly_repayment', sa.DECIMAL(precision=15, scale=2), nullable=False, server_default='0.00'))


def downgrade() -> None:
    # Remove leverage_monthly_repayment
    op.drop_column('investment', 'leverage_monthly_repayment')
    
    # Rename leverage_repayment_months back to leverage_repayment_month
    with op.batch_alter_table('investment') as batch_op:
        batch_op.alter_column('leverage_repayment_months',
                             new_column_name='leverage_repayment_month',
                             existing_type=sa.Integer(),
                             nullable=True)
