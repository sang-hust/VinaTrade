"""market regime: new highs/lows, foreign flow; longer headline

Revision ID: d1e6f9b2c748
Revises: c0d5e8f1a637
Create Date: 2026-10-20 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e6f9b2c748'
down_revision = 'c0d5e8f1a637'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('market_regime', sa.Column('new_highs', sa.Integer(), nullable=True))
    op.add_column('market_regime', sa.Column('new_lows', sa.Integer(), nullable=True))
    op.add_column('market_regime', sa.Column('foreign_net_5d', sa.Float(), nullable=True))
    op.add_column('market_regime', sa.Column('foreign_sell_streak', sa.Integer(), nullable=True))
    op.alter_column('market_regime', 'headline', type_=sa.String(length=300))
    # preset "Nên tránh" now uses the total risk score (seed only refreshes presets the admin never customised)
    op.execute("""UPDATE screeners SET name = 'Rủi ro cao, nên tránh', description = 'Điểm rủi ro tổng hợp ≥ 50 hoặc rủi ro doanh nghiệp ≥ 60 (biến động, thanh khoản, thao túng, sự kiện)',
                  conditions = '{"all": [{"any": [{"field": "risk_total", "op": ">=", "value": 50}, {"field": "risk_score", "op": ">=", "value": 60}]}]}'::json
                  WHERE code = 'HIGH_RISK' AND is_preset""")


def downgrade() -> None:
    op.alter_column('market_regime', 'headline', type_=sa.String(length=200))
    for c in ('foreign_sell_streak', 'foreign_net_5d', 'new_lows', 'new_highs'):
        op.drop_column('market_regime', c)
