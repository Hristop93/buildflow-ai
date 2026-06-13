"""procedure term basis

Revision ID: 4034885eda70
Revises: 62471412aaaa
Create Date: 2026-06-13 20:17:35.125048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4034885eda70'
down_revision: Union[str, Sequence[str], None] = '62471412aaaa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('procedures', sa.Column('term_basis', sa.String(), server_default='calendar', nullable=False), schema='core')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('procedures', 'term_basis', schema='core')
