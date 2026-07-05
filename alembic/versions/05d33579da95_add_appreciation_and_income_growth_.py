"""add_appreciation_and_income_growth_fields

Revision ID: 05d33579da95
Revises: b41d17aab32a
Create Date: 2025-11-01 13:10:56.090176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05d33579da95'
down_revision: Union[str, None] = 'b41d17aab32a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add asset appreciation/depreciation fields
    op.add_column('investment', sa.Column('asset_appreciates', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('investment', sa.Column('appreciation_rate_percent', sa.DECIMAL(precision=6, scale=3), nullable=False, server_default='0.000'))
    op.add_column('investment', sa.Column('appreciation_cadence', sa.String(), nullable=False, server_default='yearly'))
    
    # Add income growth fields
    op.add_column('investment', sa.Column('income_increases', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('investment', sa.Column('income_increase_rate_percent', sa.DECIMAL(precision=6, scale=3), nullable=False, server_default='0.000'))
    op.add_column('investment', sa.Column('income_increase_cadence', sa.String(), nullable=False, server_default='yearly'))


def downgrade() -> None:
    # Remove income growth fields
    op.drop_column('investment', 'income_increase_cadence')
    op.drop_column('investment', 'income_increase_rate_percent')
    op.drop_column('investment', 'income_increases')
    
    # Remove asset appreciation/depreciation fields
    op.drop_column('investment', 'appreciation_cadence')
    op.drop_column('investment', 'appreciation_rate_percent')
    op.drop_column('investment', 'asset_appreciates')
