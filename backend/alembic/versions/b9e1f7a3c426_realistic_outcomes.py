"""signal outcomes: realistic simulation fields

Revision ID: b9e1f7a3c426
Revises: a7d4e0c1b215
Create Date: 2026-10-20 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9e1f7a3c426'
down_revision = 'a7d4e0c1b215'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('signal_outcomes', sa.Column('entry_price', sa.Float(), nullable=True))
    op.add_column('signal_outcomes', sa.Column('exit_price', sa.Float(), nullable=True))
    op.add_column('signal_outcomes', sa.Column('exit_reason', sa.String(length=8), nullable=True))
    op.add_column('signal_outcomes', sa.Column('exit_sessions', sa.Integer(), nullable=True))


def downgrade() -> None:
    for c in ('exit_sessions', 'exit_reason', 'exit_price', 'entry_price'):
        op.drop_column('signal_outcomes', c)
