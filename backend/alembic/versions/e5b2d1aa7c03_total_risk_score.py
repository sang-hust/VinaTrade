"""total risk score + risk-adjusted ranking

Revision ID: e5b2d1aa7c03
Revises: d4a1c0ffee01
Create Date: 2026-10-19 19:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5b2d1aa7c03'
down_revision = 'd4a1c0ffee01'
branch_labels = None
depends_on = None

COLS = [('risk_total', sa.Float()), ('risk_total_level', sa.String(length=8)), ('risk_components', sa.JSON()),
        ('score_adj_short', sa.Float()), ('score_adj_mid', sa.Float()), ('score_adj_long', sa.Float())]


def upgrade() -> None:
    for table in ('stock_scores', 'stock_snapshots'):
        for name, typ in COLS:
            op.add_column(table, sa.Column(name, typ, nullable=True))
    op.create_index('ix_snap_score_adj_mid', 'stock_snapshots', ['score_adj_mid'])


def downgrade() -> None:
    op.drop_index('ix_snap_score_adj_mid', table_name='stock_snapshots')
    for table in ('stock_scores', 'stock_snapshots'):
        for name, _ in COLS:
            op.drop_column(table, name)
