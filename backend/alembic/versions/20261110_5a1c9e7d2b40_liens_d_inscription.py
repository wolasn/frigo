"""liens d'inscription

Revision ID: 5a1c9e7d2b40
Revises: 3605dc125ccb
Create Date: 2026-11-10 19:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '5a1c9e7d2b40'
down_revision: str | None = '3605dc125ccb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('signup_invitations',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_signup_invitations_created_by_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['used_by'], ['users.id'], name=op.f('fk_signup_invitations_used_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signup_invitations')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_signup_invitations_token_hash'))
    )
    op.create_index(op.f('ix_signup_invitations_created_by'), 'signup_invitations', ['created_by'], unique=False)
    op.execute('ALTER TABLE public."signup_invitations" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(op.f('ix_signup_invitations_created_by'), table_name='signup_invitations')
    op.drop_table('signup_invitations')
