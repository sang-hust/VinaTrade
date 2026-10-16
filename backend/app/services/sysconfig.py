"""system_config access with defaults (admin-editable thresholds, weights, trading parameters — BR-03..08, 4.2)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.scoring import DEFAULT_WEIGHTS
from app.engines.strategies import DEFAULT_PARAMS
from app.ingestion.icb import SECTOR_MACRO_RULES
from app.models import SystemConfig

DEFAULTS: dict[str, tuple[object, str, str]] = {
    "scoring.weights": (DEFAULT_WEIGHTS, "Trọng số điểm tổng hợp theo khung (kỹ thuật, cơ bản, ngành, nền giá & AI), tổng 100", "scoring"),
    "scoring.thresholds": ({"STRONG_BUY": 80, "BUY": 65, "HOLD": 50, "REDUCE": 35}, "Ngưỡng xếp loại khuyến nghị", "scoring"),
    "strategy.params": (DEFAULT_PARAMS, "Tham số chiến lược tín hiệu", "strategy"),
    "base.params": ({"min_length": 25, "max_depth": 0.35, "pivot_wing": 10, "breakout_vol_ratio": 1.5}, "Tham số nhận diện nền giá", "strategy"),
    "regime.equity": ({"UPTREND": 80, "PRESSURE": 60, "CORRECTION": 40, "DOWNTREND": 20}, "Tỷ trọng cổ phiếu tối đa theo trạng thái thị trường (%)", "scoring"),
    "risk.defaults": ({"max_risk_per_trade_pct": 1.5, "stop_loss_pct": 8.0, "max_position_pct": 20.0, "max_sector_pct": 40.0, "max_correlated_group_pct": 40.0,
                       "weekly_loss_limit_pct": 3.0, "monthly_loss_limit_pct": 6.0, "cooldown_sessions": 5, "min_risk_reward": 2.0},
                      "Giới hạn rủi ro mặc định cho người dùng mới", "risk"),
    "risk.company_thresholds": ({"downgrade": 60, "no_buy": 80}, "Điểm rủi ro doanh nghiệp: hạ một bậc / không phát tín hiệu mua", "risk"),
    "risk.chase": ({"SHORT": 15, "MID": 20, "ceiling_streak": 2}, "Ngưỡng mua đuổi (% cách điểm phá nền) theo khung", "risk"),
    "risk.correlation": ({"rho": 0.8, "sessions": 60}, "Ngưỡng tương quan nhóm tập trung ẩn", "risk"),
    "market.hours": ({"ato": "09:00-09:15", "morning": "09:15-11:30", "afternoon": "13:00-14:30", "atc": "14:30-14:45"}, "Giờ giao dịch HOSE", "market"),
    "market.limits": ({"HOSE": 7, "HNX": 10, "UPCOM": 15}, "Biên độ dao động (%)", "market"),
    "market.fees": ({"fee_pct": 0.15, "tax_pct": 0.1, "settlement_days": 2}, "Phí, thuế mặc định và chu kỳ thanh toán", "market"),
    "market.min_liquidity": (5_000_000_000, "GTGD TB 20 phiên tối thiểu để sinh tín hiệu (đồng)", "market"),
    "alerts.limits": ({"max_rules_per_user": 200, "max_per_day": 40, "cooldown_minutes": 1440}, "Giới hạn cảnh báo", "alerts"),
    "ai.limits": ({"daily_questions": 50, "monthly_budget_usd": 50}, "Hạn mức trợ lý AI", "ai"),
    "macro.sector_rules": (SECTOR_MACRO_RULES, "Ánh xạ yếu tố vĩ mô → ngành hưởng lợi / bất lợi", "macro"),
    "macro.active_factors": (["Đẩy mạnh đầu tư công", "Tiêu dùng phục hồi", "Nâng hạng thị trường"], "Yếu tố vĩ mô đang có hiệu lực (Admin cập nhật)", "macro"),
    "signals.explain_with_ai": (True, "Dùng AI viết câu kết luận cho mã có tín hiệu trong ngày", "ai"),
}


async def get_config(db: AsyncSession, key: str):
    row = await db.get(SystemConfig, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS[key][0] if key in DEFAULTS else None


async def all_config(db: AsyncSession) -> list[dict]:
    rows = {r.key: r for r in (await db.execute(select(SystemConfig))).scalars()}
    out = []
    for key, (default, desc, group) in DEFAULTS.items():
        r = rows.get(key)
        out.append({"key": key, "value": r.value if r else default, "default": default, "description": desc, "group": group,
                    "updated_by": r.updated_by if r else None, "updated_at": r.updated_at.isoformat() if r and r.updated_at else None})
    return out


async def set_config(db: AsyncSession, key: str, value, by: str | None) -> None:
    row = await db.get(SystemConfig, key)
    if row is None:
        d = DEFAULTS.get(key, (None, None, None))
        row = SystemConfig(key=key, description=d[1], group=d[2])
        db.add(row)
    row.value, row.updated_by = value, by
    await db.flush()
