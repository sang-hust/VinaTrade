"""signal reliability: stop rate, tail returns, avg gain/loss

Revision ID: f6c3a9d2b104
Revises: e5b2d1aa7c03
Create Date: 2026-10-19 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6c3a9d2b104'
down_revision = 'e5b2d1aa7c03'
branch_labels = None
depends_on = None

COLS = ['stop_rate', 'tp1_rate', 'p05_return', 'worst_return', 'avg_gain', 'avg_loss']


def upgrade() -> None:
    for c in COLS:
        op.add_column('signal_reliability', sa.Column(c, sa.Float(), nullable=True))


def downgrade() -> None:
    for c in COLS:
        op.drop_column('signal_reliability', c)
