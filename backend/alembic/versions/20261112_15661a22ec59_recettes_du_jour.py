"""recettes du jour

Revision ID: 15661a22ec59
Revises: 5a1c9e7d2b40
Create Date: 2026-11-12 10:59:21.724219
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '15661a22ec59'
down_revision: str | None = '5a1c9e7d2b40'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('daily_recipes',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('recipe_id', sa.UUID(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('query', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin in ('base', 'marmiton', 'ia')", name=op.f('ck_daily_recipes_origin')),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], name=op.f('fk_daily_recipes_recipe_id_recipes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_daily_recipes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'day', 'position', name=op.f('pk_daily_recipes'))
    )
    op.create_index(op.f('ix_daily_recipes_recipe_id'), 'daily_recipes', ['recipe_id'], unique=False)
    op.execute('ALTER TABLE public."daily_recipes" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(op.f('ix_daily_recipes_recipe_id'), table_name='daily_recipes')
    op.drop_table('daily_recipes')
