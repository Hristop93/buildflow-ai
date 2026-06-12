"""rule conditions json

Revision ID: 08930e3e31ae
Revises: 8f10d5ff6b07
Create Date: 2026-06-12 15:44:10.420207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08930e3e31ae'
down_revision: Union[str, Sequence[str], None] = '8f10d5ff6b07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rules', sa.Column('conditions', sa.JSON(), nullable=True), schema='core')
    # Compound rules carry their condition in `conditions`; the legacy triple
    # becomes optional.
    op.alter_column('rules', 'param_name', nullable=True, schema='core')
    op.alter_column('rules', 'operator', nullable=True, schema='core')
    op.alter_column('rules', 'value', nullable=True, schema='core')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('rules', 'value', nullable=False, schema='core')
    op.alter_column('rules', 'operator', nullable=False, schema='core')
    op.alter_column('rules', 'param_name', nullable=False, schema='core')
    op.drop_column('rules', 'conditions', schema='core')
