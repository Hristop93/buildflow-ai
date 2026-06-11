"""add user role

Revision ID: 6b943d6c0044
Revises: 00c0ddea80b6
Create Date: 2026-06-10 23:52:07.389329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b943d6c0044'
down_revision: Union[str, Sequence[str], None] = '00c0ddea80b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('role', sa.String(), server_default='user', nullable=False), schema='app')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'role', schema='app')
