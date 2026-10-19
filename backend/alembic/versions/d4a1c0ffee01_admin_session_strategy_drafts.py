"""admin session idle lock, strategy drafts

Revision ID: d4a1c0ffee01
Revises: b32018055276
Create Date: 2026-10-19 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a1c0ffee01'
down_revision = 'b32018055276'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_devices', sa.Column('admin_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('strategies', sa.Column('draft_params', sa.JSON(), nullable=True))
    op.add_column('strategies', sa.Column('draft_backtest', sa.JSON(), nullable=True))
    op.add_column('strategies', sa.Column('draft_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('strategies', 'draft_updated_at')
    op.drop_column('strategies', 'draft_backtest')
    op.drop_column('strategies', 'draft_params')
    op.drop_column('user_devices', 'admin_seen_at')
