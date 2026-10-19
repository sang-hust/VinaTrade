"""11 preset screeners (spec 5.5) + form ↔ DSL mapping (BR-21)."""

FORM_FIELDS = [
    {"key": "exchange", "label": "Sàn", "multi": True, "level": "SIMPLE",
     "options": [{"v": "HOSE", "label": "HOSE"}, {"v": "HNX", "label": "HNX"}, {"v": "UPCOM", "label": "UPCoM"}]},
    {"key": "value_ma20", "label": "GTGD TB 20 phiên", "level": "SIMPLE",
     "options": [{"v": 5e9, "label": "≥ 5 tỷ"}, {"v": 2e10, "label": "≥ 20 tỷ"}, {"v": 5e10, "label": "≥ 50 tỷ"}]},
    {"key": "trend", "label": "Xu hướng trung hạn", "level": "SIMPLE",
     "options": [{"v": "UP", "label": "Tăng"}, {"v": "ANY", "label": "Bất kỳ"}, {"v": "DOWN", "label": "Giảm"}]},
    {"key": "dist_ma50", "label": "Khoảng cách tới MA50", "level": "SIMPLE",
     "options": [{"v": "NEAR", "label": "Gần MA50 (−3% đến +2%)"}, {"v": "ANY", "label": "Bất kỳ"}]},
    {"key": "rsi", "label": "RSI (14)", "level": "SIMPLE",
     "options": [{"v": "LT35", "label": "Dưới 35"}, {"v": "35_55", "label": "35–55"}, {"v": "50_75", "label": "50–75"}, {"v": "ANY", "label": "Bất kỳ"}]},
    {"key": "min_score", "label": "Điểm tối thiểu", "level": "SIMPLE",
     "options": [{"v": 0, "label": "Bất kỳ"}, {"v": 50, "label": "50"}, {"v": 65, "label": "65"}, {"v": 80, "label": "80"}]},
    {"key": "risk", "label": "Rủi ro doanh nghiệp", "level": "STANDARD",
     "options": [{"v": "ANY", "label": "Bất kỳ"}, {"v": 60, "label": "Dưới 60"}, {"v": 35, "label": "Dưới 35"}]},
    {"key": "pe", "label": "P/E", "level": "STANDARD",
     "options": [{"v": "ANY", "label": "Bất kỳ"}, {"v": 15, "label": "Đến 15"}, {"v": 25, "label": "Đến 25"}]},
    {"key": "roe", "label": "ROE", "level": "STANDARD",
     "options": [{"v": "ANY", "label": "Bất kỳ"}, {"v": 15, "label": "Từ 15%"}, {"v": 20, "label": "Từ 20%"}]},
    {"key": "no_chase", "label": "Bỏ mã mua đuổi", "level": "SIMPLE", "toggle": True},
]

DEFAULT_FORM = {"exchange": ["HOSE", "HNX", "UPCOM"], "value_ma20": 5e9, "trend": "ANY", "dist_ma50": "ANY", "rsi": "ANY",
                "min_score": 0, "risk": "ANY", "pe": "ANY", "roe": "ANY", "no_chase": True}


def form_to_rules(form: dict, horizon: str = "MID") -> list[dict]:
    f = {**DEFAULT_FORM, **(form or {})}
    rules: list[dict] = []
    if f.get("exchange") and len(f["exchange"]) < 3:
        rules.append({"field": "exchange", "op": "in", "value": list(f["exchange"])})
    if f.get("value_ma20"):
        rules.append({"field": "value_ma20", "op": ">=", "value": float(f["value_ma20"])})
    if f.get("trend") == "UP":
        rules.append({"field": "trend_state", "op": "in", "value": ["UP", "STRONG_UP"]})
    elif f.get("trend") == "DOWN":
        rules.append({"field": "trend_state", "op": "in", "value": ["DOWN", "STRONG_DOWN"]})
    if f.get("dist_ma50") == "NEAR":
        rules.append({"field": "dist_ma50_pct", "op": "between", "value": [-3, 2]})
    rsi = f.get("rsi")
    if rsi == "LT35":
        rules.append({"field": "rsi14", "op": "<", "value": 35})
    elif rsi == "35_55":
        rules.append({"field": "rsi14", "op": "between", "value": [35, 55]})
    elif rsi == "50_75":
        rules.append({"field": "rsi14", "op": "between", "value": [50, 75]})
    if f.get("min_score"):
        rules.append({"field": f"score_{horizon.lower()}", "op": ">=", "value": float(f["min_score"])})
    if f.get("risk") not in (None, "ANY"):
        rules.append({"field": "risk_score", "op": "<", "value": float(f["risk"])})
    if f.get("pe") not in (None, "ANY"):
        rules.append({"field": "pe", "op": "between", "value": [0, float(f["pe"])]})
    if f.get("roe") not in (None, "ANY"):
        rules.append({"field": "roe", "op": ">=", "value": float(f["roe"])})
    if f.get("no_chase", True):
        rules.append({"field": "gain_from_base_pct", "op": "<=", "value": 15 if horizon == "SHORT" else 20})
    return rules


def build_dsl(core: list[dict], form: dict | None, horizon: str) -> dict:
    """Core preset rules AND form rules; a form rule on the same field overrides the core rule."""
    form_rules = form_to_rules(form, horizon) if form is not None else []
    form_fields = {r["field"] for r in form_rules}
    merged = [r for r in core if r.get("field") is None or r["field"] not in form_fields] + form_rules  # nested any/all rules pass through
    return {"all": merged}


PRESETS = [
    {"code": "PULLBACK_MA50", "name": "Điều chỉnh về MA50 trong xu hướng tăng", "group": "TECH", "horizon": "MID",
     "description": "MA50 đang dốc lên, giá về sát MA50, RSI 35–55, thanh khoản tốt",
     "core": [{"field": "ma50_slope", "op": ">", "value": 0}],
     "form": {"trend": "UP", "dist_ma50": "NEAR", "rsi": "35_55", "value_ma20": 2e10}},
    {"code": "BREAKOUT_VOL", "name": "Vượt đỉnh kèm khối lượng", "group": "TECH", "horizon": "SHORT",
     "description": "Giá ≥ đỉnh 52 tuần, khối lượng ≥ 1,5 lần trung bình 20 phiên",
     "core": [{"field": "price", "op": ">=", "value": {"field": "high_52w"}}, {"field": "vol_ratio", "op": ">=", "value": 1.5}],
     "form": {"trend": "UP", "value_ma20": 5e9}},
    {"code": "BASE_QUALITY", "name": "Phá nền trung hạn chất lượng", "group": "TECH", "horizon": "MID",
     "description": "Phá nền ≥ 40 phiên trong 3 phiên gần nhất, KL ≥ 1,5 lần, ROE ≥ 15%, rủi ro thấp",
     "core": [{"field": "signal", "op": "has_signal", "value": "BREAKOUT_BASE", "lookback": 3},
              {"field": "base_length_days", "op": ">=", "value": 40}, {"field": "vol_ratio", "op": ">=", "value": 1.5}],
     "form": {"trend": "UP", "rsi": "50_75", "min_score": 65, "risk": 60, "roe": 15, "value_ma20": 5e9}},
    {"code": "TIGHT_BASE", "name": "Nền giá tích lũy chặt", "group": "TECH", "horizon": "MID",
     "description": "Nền đang hình thành, biên độ 10 phiên ≤ 3%, khối lượng cạn ≤ 0,8 lần TB20",
     "core": [{"field": "base_status", "op": "==", "value": "FORMING"}, {"field": "base_tightness", "op": "<=", "value": 3},
              {"field": "vol_ratio", "op": "<=", "value": 0.8}, {"field": "price", "op": ">", "value": {"field": "ma50"}}],
     "form": {"value_ma20": 5e9}},
    {"code": "GOLDEN_CROSS", "name": "MA50 vừa cắt lên MA200", "group": "TECH", "horizon": "LONG",
     "description": "MA50 cắt lên MA200 trong 10 phiên gần nhất",
     "core": [{"field": "ma50", "op": "cross_above", "value": {"field": "ma200"}, "lookback": 10}],
     "form": {"value_ma20": 5e9}},
    {"code": "RSI_OVERSOLD", "name": "RSI quá bán", "group": "TECH", "horizon": "SHORT",
     "description": "RSI dưới 35 ở doanh nghiệp không rủi ro cao",
     "core": [], "form": {"rsi": "LT35", "risk": 60, "value_ma20": 5e9, "no_chase": False}},
    {"code": "CANSLIM", "name": "Tăng trưởng (CANSLIM)", "group": "FUND", "horizon": "MID",
     "description": "Lợi nhuận quý ≥ 25% so cùng kỳ, RS ≥ 80, ROE ≥ 15%",
     "core": [{"field": "profit_yoy", "op": ">=", "value": 25}, {"field": "rs_rating", "op": ">=", "value": 80}],
     "form": {"roe": 15, "value_ma20": 5e9}},
    {"code": "GRAHAM", "name": "Giá trị (Graham)", "group": "FUND", "horizon": "LONG",
     "description": "P/E 0–12, P/B ≤ 1,5, nợ vay/vốn chủ ≤ 1",
     "core": [{"field": "pe", "op": "between", "value": [0, 12]}, {"field": "pb", "op": "<=", "value": 1.5},
              {"field": "debt_to_equity", "op": "<=", "value": 1}],
     "form": {"value_ma20": 5e9, "no_chase": False}},
    {"code": "DIVIDEND", "name": "Cổ tức cao, ổn định", "group": "FUND", "horizon": "LONG",
     "description": "Tỷ suất cổ tức ≥ 6%, dòng tiền kinh doanh / lợi nhuận ≥ 0,8, ROE ≥ 15%",
     "core": [{"field": "dividend_yield", "op": ">=", "value": 6}, {"field": "cfo_to_profit", "op": ">=", "value": 0.8}],
     "form": {"roe": 15, "value_ma20": 5e9, "no_chase": False}},
    {"code": "DEATH_CROSS", "name": "MA50 cắt xuống MA200", "group": "AVOID", "horizon": "LONG",
     "description": "MA50 cắt xuống MA200 trong 10 phiên gần nhất",
     "core": [{"field": "ma50", "op": "cross_below", "value": {"field": "ma200"}, "lookback": 10}],
     "form": {"value_ma20": 5e9, "no_chase": False}},
    {"code": "HIGH_RISK", "name": "Rủi ro cao, nên tránh", "group": "AVOID", "horizon": "LONG",
     "description": "Điểm rủi ro tổng hợp ≥ 50 hoặc rủi ro doanh nghiệp ≥ 60 (biến động, thanh khoản, thao túng, sự kiện)",
     "core": [{"any": [{"field": "risk_total", "op": ">=", "value": 50}, {"field": "risk_score", "op": ">=", "value": 60}]}],
     "form": {"value_ma20": 5e9, "no_chase": False}},
]
