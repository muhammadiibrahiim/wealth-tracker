"""add_total_inflows_to_investment_metrics

Revision ID: 99d56ea97b64
Revises: b6b4423a3589
Create Date: 2025-11-01 14:18:26.449687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99d56ea97b64'
down_revision: Union[str, None] = 'b6b4423a3589'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add total_inflows column to investment_metric table
    op.add_column('investment_metric', sa.Column('total_inflows', sa.DECIMAL(15, 2), nullable=True))


def downgrade() -> None:
    # Remove total_inflows column from investment_metric table
    op.drop_column('investment_metric', 'total_inflows')
