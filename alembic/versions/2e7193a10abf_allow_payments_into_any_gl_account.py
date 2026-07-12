"""allow payments into any gl account

Revision ID: 2e7193a10abf
Revises: 3c6238d5d0c2
Create Date: 2026-07-10 17:37:00.343676

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e7193a10abf'
down_revision: Union[str, None] = '3c6238d5d0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("trade_payments") as batch_op:
        batch_op.alter_column("cash_account_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_trade_payments_account_id_accounts", "accounts", ["account_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("trade_payments") as batch_op:
        batch_op.drop_constraint("fk_trade_payments_account_id_accounts", type_="foreignkey")
        batch_op.drop_column("account_id")
        batch_op.alter_column("cash_account_id", existing_type=sa.Integer(), nullable=False)
