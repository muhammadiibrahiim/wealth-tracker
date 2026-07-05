"""add_pv_inflows_to_investment_metrics

Revision ID: b6b4423a3589
Revises: 05d33579da95
Create Date: 2025-11-01 14:03:00.579262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6b4423a3589'
down_revision: Union[str, None] = '05d33579da95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pv_inflows column to investment_metric table
    op.add_column('investment_metric', sa.Column('pv_inflows', sa.DECIMAL(15, 2), nullable=True))


def downgrade() -> None:
    # Remove pv_inflows column from investment_metric table
    op.drop_column('investment_metric', 'pv_inflows')
