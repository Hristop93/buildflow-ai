"""tiered fee tariffs

Revision ID: 40f511274b7a
Revises: 08930e3e31ae
Create Date: 2026-06-13 19:56:37.267932

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40f511274b7a'
down_revision: Union[str, Sequence[str], None] = '08930e3e31ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('fee_tariffs', sa.Column('tiers', sa.JSON(), nullable=True), schema='core')
    op.add_column('fee_tariffs', sa.Column('min_fee', sa.Float(), nullable=True), schema='core')
    op.add_column('fee_tariffs', sa.Column('max_fee', sa.Float(), nullable=True), schema='core')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('fee_tariffs', 'max_fee', schema='core')
    op.drop_column('fee_tariffs', 'min_fee', schema='core')
    op.drop_column('fee_tariffs', 'tiers', schema='core')
