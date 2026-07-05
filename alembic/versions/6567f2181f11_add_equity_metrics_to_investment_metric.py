"""add_equity_metrics_to_investment_metric

Revision ID: 6567f2181f11
Revises: a208bbfd4abc
Create Date: 2025-11-01 16:52:01.034228

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6567f2181f11'
down_revision: Union[str, None] = 'a208bbfd4abc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add equity metrics columns to investment_metric table
    op.add_column('investment_metric', sa.Column('equity_roi_percent', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_npv', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_irr_percent', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_mirr_percent', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_profitability_index', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_payback_months', sa.Float(), nullable=True))
    op.add_column('investment_metric', sa.Column('equity_discounted_payback_months', sa.Float(), nullable=True))


def downgrade() -> None:
    # Remove equity metrics columns
    op.drop_column('investment_metric', 'equity_discounted_payback_months')
    op.drop_column('investment_metric', 'equity_payback_months')
    op.drop_column('investment_metric', 'equity_profitability_index')
    op.drop_column('investment_metric', 'equity_mirr_percent')
    op.drop_column('investment_metric', 'equity_irr_percent')
    op.drop_column('investment_metric', 'equity_npv')
    op.drop_column('investment_metric', 'equity_roi_percent')
