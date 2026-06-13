"""dependency link type and lag

Revision ID: 62471412aaaa
Revises: 40f511274b7a
Create Date: 2026-06-13 20:06:39.715527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62471412aaaa'
down_revision: Union[str, Sequence[str], None] = '40f511274b7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('dependencies', sa.Column('lag_days', sa.Integer(), server_default='0', nullable=False), schema='core')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('dependencies', 'lag_days', schema='core')
