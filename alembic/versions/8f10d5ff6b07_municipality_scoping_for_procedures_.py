"""municipality scoping for procedures rules dependencies

Revision ID: 8f10d5ff6b07
Revises: fa5f60d33312
Create Date: 2026-06-12 09:09:49.766217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f10d5ff6b07'
down_revision: Union[str, Sequence[str], None] = 'fa5f60d33312'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('procedures', sa.Column('municipality_id', sa.Integer(), nullable=True), schema='core')
    op.create_foreign_key('fk_procedures_municipality', 'procedures', 'municipalities',
                          ['municipality_id'], ['id'], source_schema='core', referent_schema='core')
    op.add_column('dependencies', sa.Column('municipality_id', sa.Integer(), nullable=True), schema='core')
    op.create_foreign_key('fk_dependencies_municipality', 'dependencies', 'municipalities',
                          ['municipality_id'], ['id'], source_schema='core', referent_schema='core')
    op.add_column('rules', sa.Column('municipality_id', sa.Integer(), nullable=True), schema='core')
    op.create_foreign_key('fk_rules_municipality', 'rules', 'municipalities',
                          ['municipality_id'], ['id'], source_schema='core', referent_schema='core')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_rules_municipality', 'rules', schema='core', type_='foreignkey')
    op.drop_column('rules', 'municipality_id', schema='core')
    op.drop_constraint('fk_dependencies_municipality', 'dependencies', schema='core', type_='foreignkey')
    op.drop_column('dependencies', 'municipality_id', schema='core')
    op.drop_constraint('fk_procedures_municipality', 'procedures', schema='core', type_='foreignkey')
    op.drop_column('procedures', 'municipality_id', schema='core')
