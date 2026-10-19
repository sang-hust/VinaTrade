"""plan.params defaults: min_risk_reward 2.0 → 1.5 for users still on the old default

Revision ID: c0d5e8f1a637
Revises: b9e1f7a3c426
Create Date: 2026-10-20 11:00:00
"""
from alembic import op


revision = 'c0d5e8f1a637'
down_revision = 'b9e1f7a3c426'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE user_risk_limits SET min_risk_reward = 1.5 WHERE min_risk_reward = 2.0")


def downgrade() -> None:
    pass
