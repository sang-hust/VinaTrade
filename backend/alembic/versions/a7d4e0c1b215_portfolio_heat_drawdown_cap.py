"""portfolio heat cap + drawdown-based equity cap

Revision ID: a7d4e0c1b215
Revises: f6c3a9d2b104
Create Date: 2026-10-19 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7d4e0c1b215'
down_revision = 'f6c3a9d2b104'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_risk_limits', sa.Column('max_open_risk_pct', sa.Numeric(6, 3), nullable=False, server_default='6'))
    op.add_column('risk_guard_status', sa.Column('drawdown_pct', sa.Numeric(8, 3), nullable=True))
    op.add_column('risk_guard_status', sa.Column('peak_nav', sa.Numeric(18, 0), nullable=True))
    op.add_column('risk_guard_status', sa.Column('equity_cap_pct', sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('risk_guard_status', 'equity_cap_pct')
    op.drop_column('risk_guard_status', 'peak_nav')
    op.drop_column('risk_guard_status', 'drawdown_pct')
    op.drop_column('user_risk_limits', 'max_open_risk_pct')
