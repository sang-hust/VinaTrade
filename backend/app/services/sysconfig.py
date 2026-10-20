"""system_config access with defaults (admin-editable thresholds, weights, trading parameters — BR-03..08, 4.2)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.regime import DEFAULT_BREADTH_PARAMS
from app.engines.risk import DEFAULT_REGIME_GATE, DEFAULT_RISK_PARAMS, DEFAULT_RISK_WEIGHTS
from app.engines.scoring import DEFAULT_PLAN_PARAMS, DEFAULT_WEIGHTS
from app.engines.strategies import DEFAULT_PARAMS
from app.ingestion.icb import SECTOR_MACRO_RULES
from app.models import SystemConfig

DEFAULTS: dict[str, tuple[object, str, str]] = {
    "scoring.weights": (DEFAULT_WEIGHTS, "Trọng số điểm tổng hợp theo khung (kỹ thuật, cơ bản, ngành, nền giá & AI), tổng 100", "scoring"),
    "scoring.thresholds": ({"STRONG_BUY": 80, "BUY": 65, "HOLD": 50, "REDUCE": 35}, "Ngưỡng xếp loại khuyến nghị", "scoring"),
    "strategy.params": (DEFAULT_PARAMS, "Tham số chiến lược tín hiệu", "strategy"),
    "strategy.regime_gate": (DEFAULT_REGIME_GATE, "Tự 'đứng ngoài' tín hiệu của chiến lược có kỳ vọng âm ở trạng thái thị trường hiện tại", "strategy"),
    "plan.params": (DEFAULT_PLAN_PARAMS, "Đặt cắt lỗ / chốt lời cho kế hoạch giao dịch (nghiên cứu 4b)", "strategy"),
    "base.params": ({"min_length": 25, "max_depth": 0.35, "pivot_wing": 10, "breakout_vol_ratio": 1.5}, "Tham số nhận diện nền giá", "strategy"),
    "regime.equity": ({"UPTREND": 80, "PRESSURE": 60, "CORRECTION": 40, "DOWNTREND": 20}, "Tỷ trọng cổ phiếu tối đa theo trạng thái thị trường (%)", "scoring"),
    "regime.breadth": (DEFAULT_BREADTH_PARAMS, "Độ rộng thị trường và khối ngoại hạ trạng thái Tăng → Chịu áp lực", "scoring"),
    "risk.manipulation": ({"warn": 30, "block": 60}, "Điểm dấu hiệu thao túng: cảnh báo Vàng / chặn mua (Đỏ, không phát tín hiệu mua)", "risk"),
    "risk.defaults": ({"max_risk_per_trade_pct": 1.5, "stop_loss_pct": 8.0, "max_position_pct": 20.0, "max_sector_pct": 40.0, "max_correlated_group_pct": 40.0,
                       "weekly_loss_limit_pct": 3.0, "monthly_loss_limit_pct": 6.0, "cooldown_sessions": 5, "min_risk_reward": 1.5, "max_open_risk_pct": 6.0},
                      "Giới hạn rủi ro mặc định cho người dùng mới", "risk"),
    "risk.company_thresholds": ({"downgrade": 60, "no_buy": 80}, "Điểm rủi ro doanh nghiệp: hạ một bậc / không phát tín hiệu mua", "risk"),
    "risk.drawdown_steps": ({"dd1": 5.0, "cap1": 50.0, "dd2": 10.0, "cap2": 25.0}, "Giảm tỷ trọng theo sụt giảm từ đỉnh: giảm ≥ dd1% → tối đa cap1% cổ phiếu; ≥ dd2% → cap2%", "risk"),
    "risk.chase": ({"SHORT": 15, "MID": 20, "ceiling_streak": 2}, "Ngưỡng mua đuổi (% cách điểm phá nền) theo khung", "risk"),
    "risk.correlation": ({"rho": 0.8, "sessions": 60}, "Ngưỡng tương quan nhóm tập trung ẩn", "risk"),
    "risk.score_weights": (DEFAULT_RISK_WEIGHTS, "Trọng số 6 thành phần của điểm rủi ro tổng hợp (tổng 100)", "risk"),
    "risk.score_params": (DEFAULT_RISK_PARAMS, "Ngưỡng của điểm rủi ro tổng hợp và cỡ lệnh tham chiếu", "risk"),
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


def _f(key: str, label: str, unit: str = "", type_: str = "number", **kw) -> dict:
    return {"key": key, "label": label, "unit": unit, "type": type_, **kw}


# Field metadata for the admin form (A05): label, unit and type per field. kind: form (flat fields) | weights (A03)
# | list (strings) | json (free-form). Keys not listed here fall back to the JSON editor.
CONFIG_META: dict[str, dict] = {
    "scoring.weights": {"label": "Trọng số điểm tổng hợp", "kind": "weights", "screen": "strategies"},
    "scoring.thresholds": {"label": "Ngưỡng xếp loại khuyến nghị", "kind": "form", "fields": [
        _f("STRONG_BUY", "Mua mạnh từ", "điểm", min=0, max=100), _f("BUY", "Tích lũy từ", "điểm", min=0, max=100),
        _f("HOLD", "Nắm giữ từ", "điểm", min=0, max=100), _f("REDUCE", "Giảm tỷ trọng từ", "điểm", min=0, max=100, help="Dưới mức này là Bán")]},
    "regime.equity": {"label": "Tỷ trọng cổ phiếu tối đa theo trạng thái thị trường", "kind": "form", "fields": [
        _f("UPTREND", "Thị trường tăng", "%"), _f("PRESSURE", "Chịu áp lực", "%"), _f("CORRECTION", "Điều chỉnh", "%"), _f("DOWNTREND", "Thị trường giảm", "%")]},
    "strategy.params": {"label": "Tham số chiến lược tín hiệu", "kind": "form", "fields": [
        _f("breakout_vol_ratio", "KL phá nền so với TB20", "lần", step=0.1), _f("take_profit_ratio", "Mức tăng so với trung vị đợt trước để chốt lời", "lần", step=0.05),
        _f("take_profit_rsi", "RSI chốt lời", ""), _f("take_profit_dist_ma50", "Cách MA50 để chốt lời", "%"), _f("distribution_days", "Số phiên phân phối trong 20 phiên", "phiên", type_="int"),
        _f("pullback_rsi_max", "RSI tối đa khi hồi về MA50", ""), _f("pullback_dist_ma50", "Khoảng cách tới MA50 (hồi về)", "%", type_="range"),
        _f("tight_base_tightness", "Biên độ nền chặt tối đa", "%", step=0.1), _f("tight_base_vol", "KL so với TB20 (nền chặt)", "lần", step=0.1),
        _f("chase_short", "Mua đuổi khung ngắn", "%"), _f("chase_mid", "Mua đuổi khung trung", "%")]},
    "strategy.regime_gate": {"label": "Chọn lọc chiến lược theo trạng thái thị trường", "kind": "form", "fields": [
        _f("enabled", "Bật (1) / tắt (0)", "", type_="int", min=0, max=1), _f("min_samples", "Số lần tối thiểu để kết luận", "lần", type_="int"),
        _f("min_expectancy", "Kỳ vọng tối thiểu mỗi lệnh (dưới mức này → đứng ngoài)", "%", step=0.25, help="0 = chỉ gợi ý khi lịch sử không lỗ")]},
    "plan.params": {"label": "Cắt lỗ / chốt lời của kế hoạch giao dịch", "kind": "form", "fields": [
        _f("atr_mult", "Khoảng cách cắt lỗ theo ATR", "× ATR14", step=0.25), _f("stop_floor_pct", "Cắt lỗ tối thiểu", "% giá", step=0.5), _f("stop_cap_pct", "Cắt lỗ tối đa", "% giá", step=0.5),
        _f("use_support", "Nới xuống dưới hỗ trợ gần nhất (1 = có, 0 = không)", "", type_="int", min=0, max=1), _f("tp_rr", "Chốt lời 1 = bội số rủi ro", "× rủi ro", step=0.25, help="Mặc định theo nghiên cứu: cắt lỗ ~5%, chốt lời 1,5R")]},
    "base.params": {"label": "Nhận diện nền giá", "kind": "form", "fields": [
        _f("min_length", "Độ dài nền tối thiểu", "phiên", type_="int"), _f("max_depth", "Độ sâu nền tối đa", "tỷ lệ", step=0.01),
        _f("pivot_wing", "Số phiên hai bên đỉnh/đáy", "phiên", type_="int"), _f("breakout_vol_ratio", "KL phá nền so với TB20", "lần", step=0.1)]},
    "regime.breadth": {"label": "Độ rộng thị trường & khối ngoại", "kind": "form", "fields": [
        _f("narrow_ma50_pct", "Độ rộng hẹp: dưới % mã trên MA50", "%"), _f("new_lows_ratio", "Đáy 52 tuần gấp mấy lần đỉnh", "lần", step=0.5), _f("new_lows_min", "Số mã lập đáy tối thiểu", "mã", type_="int"),
        _f("foreign_sell_days", "Khối ngoại bán ròng liên tiếp từ", "phiên", type_="int"), _f("foreign_sell_5d_vnd", "Bán ròng 5 phiên từ", "đồng", type_="int")]},
    "risk.manipulation": {"label": "Dấu hiệu thao túng", "kind": "form", "fields": [_f("warn", "Cảnh báo Vàng từ", "điểm"), _f("block", "Chặn mua (Đỏ) từ", "điểm")]},
    "risk.defaults": {"label": "Giới hạn rủi ro mặc định cho người dùng mới", "kind": "form", "fields": [
        _f("max_risk_per_trade_pct", "Lỗ tối đa mỗi lệnh", "% tài sản", step=0.1), _f("stop_loss_pct", "Cắt lỗ mặc định", "%", step=0.5),
        _f("max_position_pct", "Tỷ trọng một mã tối đa", "%"), _f("max_sector_pct", "Tỷ trọng một ngành tối đa", "%"), _f("max_correlated_group_pct", "Nhóm tương quan tối đa", "%"),
        _f("weekly_loss_limit_pct", "Giới hạn lỗ tuần", "%", step=0.5), _f("monthly_loss_limit_pct", "Giới hạn lỗ tháng", "%", step=0.5),
        _f("cooldown_sessions", "Nghỉ sau khi chạm giới hạn", "phiên", type_="int"), _f("min_risk_reward", "Tỷ lệ lợi nhuận/rủi ro tối thiểu", "lần", step=0.1),
        _f("max_open_risk_pct", "Nhiệt danh mục tối đa (tổng lỗ nếu mọi mã chạm cắt lỗ)", "% tài sản", step=0.5)]},
    "risk.drawdown_steps": {"label": "Giảm tỷ trọng theo sụt giảm từ đỉnh", "kind": "form", "fields": [
        _f("dd1", "Bậc 1: danh mục giảm từ đỉnh", "%", step=0.5), _f("cap1", "→ tối đa cổ phiếu", "% tài sản"), _f("dd2", "Bậc 2: danh mục giảm từ đỉnh", "%", step=0.5), _f("cap2", "→ tối đa cổ phiếu", "% tài sản")]},
    "risk.company_thresholds": {"label": "Điểm rủi ro doanh nghiệp", "kind": "form", "fields": [
        _f("downgrade", "Hạ một bậc khuyến nghị từ", "điểm"), _f("no_buy", "Không phát tín hiệu mua từ", "điểm")]},
    "risk.chase": {"label": "Ngưỡng mua đuổi", "kind": "form", "fields": [
        _f("SHORT", "Khung ngắn: cách điểm phá nền", "%"), _f("MID", "Khung trung: cách điểm phá nền", "%"), _f("ceiling_streak", "Số phiên trần liên tiếp", "phiên", type_="int")]},
    "risk.score_weights": {"label": "Điểm rủi ro tổng hợp: trọng số thành phần", "kind": "form", "fields": [
        _f("volatility", "Biến động", "%"), _f("liquidity", "Thanh khoản", "%"), _f("company", "Doanh nghiệp", "%"), _f("manipulation", "Dấu hiệu thao túng", "%"),
        _f("event", "Sự kiện sắp tới", "%"), _f("correlation", "Tương quan", "%", help="Tổng 6 trọng số phải bằng 100")]},
    "risk.score_params": {"label": "Điểm rủi ro tổng hợp: ngưỡng", "kind": "form", "fields": [
        _f("order_value_vnd", "Cỡ lệnh tham chiếu (so với GTGD)", "đồng", type_="int"), _f("medium_from", "Rủi ro trung bình từ", "điểm"), _f("high_from", "Rủi ro cao từ", "điểm"),
        _f("downgrade_from", "Hạ một bậc khuyến nghị từ", "điểm"), _f("atr_pct_high", "Biến động/phiên coi là cao", "%", step=0.5), _f("drawdown_high", "Sụt giảm 12 tháng coi là cao", "%"),
        _f("gain20_hot", "Tăng 20 phiên coi là nóng", "%"), _f("ceiling_streak_hot", "Chuỗi trần coi là nóng", "phiên", type_="int")]},
    "risk.correlation": {"label": "Tương quan nhóm tập trung ẩn", "kind": "form", "fields": [
        _f("rho", "Hệ số tương quan từ", "", step=0.05, min=0, max=1), _f("sessions", "Số phiên tính tương quan", "phiên", type_="int")]},
    "market.hours": {"label": "Giờ giao dịch HOSE", "kind": "form", "fields": [
        _f("ato", "Phiên ATO", "", type_="text"), _f("morning", "Phiên sáng", "", type_="text"), _f("afternoon", "Phiên chiều", "", type_="text"), _f("atc", "Phiên ATC", "", type_="text")]},
    "market.limits": {"label": "Biên độ dao động", "kind": "form", "fields": [_f("HOSE", "HOSE", "%"), _f("HNX", "HNX", "%"), _f("UPCOM", "UPCOM", "%")]},
    "market.fees": {"label": "Phí, thuế và thanh toán", "kind": "form", "fields": [
        _f("fee_pct", "Phí giao dịch", "%", step=0.01), _f("tax_pct", "Thuế bán", "%", step=0.01), _f("settlement_days", "Chu kỳ thanh toán", "ngày (T+)", type_="int")]},
    "market.min_liquidity": {"label": "Thanh khoản tối thiểu để sinh tín hiệu", "kind": "scalar", "unit": "đồng/phiên", "type": "int"},
    "alerts.limits": {"label": "Giới hạn cảnh báo", "kind": "form", "fields": [
        _f("max_rules_per_user", "Quy tắc tối đa mỗi người", "quy tắc", type_="int"), _f("max_per_day", "Cảnh báo tối đa mỗi ngày", "cảnh báo", type_="int"),
        _f("cooldown_minutes", "Không lặp cùng cảnh báo trong", "phút", type_="int")]},
    "ai.limits": {"label": "Hạn mức trợ lý AI", "kind": "form", "fields": [
        _f("daily_questions", "Câu hỏi mỗi người mỗi ngày", "câu", type_="int"), _f("monthly_budget_usd", "Ngân sách tháng", "USD")]},
    "macro.sector_rules": {"label": "Yếu tố vĩ mô → ngành hưởng lợi / bất lợi", "kind": "json"},
    "macro.active_factors": {"label": "Yếu tố vĩ mô đang có hiệu lực", "kind": "list"},
    "signals.explain_with_ai": {"label": "AI viết câu kết luận cho mã có tín hiệu", "kind": "bool"},
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
        meta = CONFIG_META.get(key, {"label": key, "kind": "json"})
        out.append({"key": key, "value": r.value if r else default, "default": default, "description": desc, "group": group, **meta,
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
