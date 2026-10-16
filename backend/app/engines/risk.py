"""Risk engines: company risk score (4.6h), pretrade check (4.6f), guard (4.6g), margin/stress (4.6i),
correlation & chase (4.6j), signal reliability (4.6k). Pure functions over dicts / DataFrames."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.vntime import floor_lot

RISK_FLAG_TEXT = {
    "CFO_NEGATIVE": "Lợi nhuận dương nhưng dòng tiền kinh doanh âm {n} quý liên tiếp",
    "RECEIVABLES": "Phải thu tăng nhanh hơn doanh thu {v:.0f} điểm %",
    "INVENTORY": "Tồn kho tăng nhanh hơn doanh thu {v:.0f} điểm %",
    "INSIDER_SELL": "Lãnh đạo, cổ đông lớn đăng ký bán ròng",
    "PLEDGED": "Cổ phiếu bị cầm cố {v:.0f}%",
    "DILUTION": "Phát hành thêm pha loãng {v:.0f}%",
    "AUDIT": "Ý kiến kiểm toán ngoại trừ",
    "LATE_FILING": "Nộp báo cáo tài chính chậm",
    "STATUS": "Cổ phiếu thuộc diện {v}",
    "LOSS": "Lỗ ròng 4 quý gần nhất",
    "HIGH_DEBT": "Nợ vay / vốn chủ sở hữu {v:.1f} lần",
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def company_risk(ratio: dict, stock: dict, insider_net_sell_vnd: float = 0.0, pledged_pct: float = 0.0,
                 audit_qualified: bool = False, late_filing: bool = False) -> dict:
    """Returns {score, level, flags}. Inputs may be partial; missing → no points."""
    score, flags = 0.0, []
    n_cfo = ratio.get("cfo_negative_quarters") or 0
    if n_cfo >= 3 and (ratio.get("eps_ttm") or 0) > 0:
        score += 20
        flags.append({"code": "CFO_NEGATIVE", "points": 20, "text": RISK_FLAG_TEXT["CFO_NEGATIVE"].format(n=n_cfo)})
    rg = ratio.get("receivable_gap_pt")
    if rg and rg > 20:
        pts = 15 * _clamp(rg / 40)
        score += pts
        flags.append({"code": "RECEIVABLES", "points": round(pts), "text": RISK_FLAG_TEXT["RECEIVABLES"].format(v=rg)})
    ig = ratio.get("inventory_gap_pt")
    if ig and ig > 20:
        pts = 10 * _clamp(ig / 40)
        score += pts
        flags.append({"code": "INVENTORY", "points": round(pts), "text": RISK_FLAG_TEXT["INVENTORY"].format(v=ig)})
    mc = ratio.get("market_cap") or 0
    if insider_net_sell_vnd > 0 and mc > 0:
        pts = 15 * _clamp(insider_net_sell_vnd / (mc * 0.005))
        score += pts
        flags.append({"code": "INSIDER_SELL", "points": round(pts), "text": RISK_FLAG_TEXT["INSIDER_SELL"]})
    if pledged_pct > 0:
        pts = 10 * _clamp(pledged_pct / 20)
        score += pts
        flags.append({"code": "PLEDGED", "points": round(pts), "text": RISK_FLAG_TEXT["PLEDGED"].format(v=pledged_pct)})
    dil = ratio.get("dilution_pct")
    if dil and dil > 10:
        pts = 10 * _clamp(dil / 20)
        score += pts
        flags.append({"code": "DILUTION", "points": round(pts), "text": RISK_FLAG_TEXT["DILUTION"].format(v=dil)})
    if audit_qualified:
        score += 10
        flags.append({"code": "AUDIT", "points": 10, "text": RISK_FLAG_TEXT["AUDIT"]})
    if late_filing:
        score += 5
        flags.append({"code": "LATE_FILING", "points": 5, "text": RISK_FLAG_TEXT["LATE_FILING"]})
    sf = stock.get("status_flags") or []
    if sf:
        vi = {"WARNING": "cảnh báo", "CONTROL": "kiểm soát", "RESTRICTED": "hạn chế giao dịch", "SUSPENDED": "đình chỉ giao dịch"}
        pts = 5 if sf == ["WARNING"] else 15
        score += pts
        flags.append({"code": "STATUS", "points": pts, "text": RISK_FLAG_TEXT["STATUS"].format(v=", ".join(vi.get(s, s) for s in sf))})
    if (ratio.get("eps_ttm") or 0) < 0:
        score += 15
        flags.append({"code": "LOSS", "points": 15, "text": RISK_FLAG_TEXT["LOSS"]})
    de = ratio.get("debt_to_equity")
    if de is not None and de > 2.0 and not stock.get("is_bank"):
        score += 10
        flags.append({"code": "HIGH_DEBT", "points": 10, "text": RISK_FLAG_TEXT["HIGH_DEBT"].format(v=de)})
    score = min(100.0, score)
    level = "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"
    return {"score": round(score, 1), "level": level, "flags": flags}


# ---------------------------------------------------------------- pretrade check (BR-14)
CHECK_VI = {
    "REGIME": "Trạng thái thị trường",
    "RISK_TRADE": "Số tiền có thể lỗ",
    "STATUS": "Tình trạng cổ phiếu",
    "RR": "Tỷ lệ lợi nhuận/rủi ro",
    "POSITION": "Tỷ trọng mã sau khi mua",
    "SECTOR": "Tỷ trọng ngành sau khi mua",
    "EVENTS": "Sự kiện trong 5 phiên tới",
    "LIQUIDITY": "Thanh khoản để thoát lệnh",
    "CHASE": "Mua đuổi",
}


@dataclass
class PretradeInput:
    symbol: str
    quantity: int
    price: float
    stop_loss: float | None
    take_profit: float | None
    horizon: str
    equity: float  # portfolio NAV (cash + positions)
    position_value: float  # current value of this symbol in the portfolio
    sector_value: float
    regime: str
    guard_mode: str
    status_flags: list[str]
    value_ma20: float | None
    gain_from_base_pct: float | None
    ceiling_streak: int | None
    earnings_in_days: int | None
    limits: dict  # max_risk_per_trade_pct, max_position_pct, max_sector_pct, min_risk_reward
    reliability_pct: float | None = None
    reliability_samples: int | None = None
    chase_limits: tuple[int, int] = (15, 20)


def pretrade_check(i: PretradeInput) -> dict:
    items = []
    q, px = i.quantity, i.price
    stop = i.stop_loss or px * 0.93
    tp = i.take_profit or px * 1.15
    order_value = q * px
    max_loss = q * max(px - stop, 0)
    equity = max(i.equity, 1)

    def item(code, ok, value, limit, red_if_fail=False, note=None):
        level = "GREEN" if ok else ("RED" if red_if_fail else "YELLOW")
        items.append({"code": code, "name": CHECK_VI[code], "level": level, "value": value, "limit": limit, "note": note})

    item("REGIME", i.regime != "DOWNTREND", {"UPTREND": "Tăng", "PRESSURE": "Chịu áp lực", "CORRECTION": "Điều chỉnh", "DOWNTREND": "Giảm"}.get(i.regime, i.regime),
         "Không ở xu hướng giảm", red_if_fail=True)
    risk_pct = max_loss / equity * 100
    item("RISK_TRADE", risk_pct <= float(i.limits.get("max_risk_per_trade_pct", 1.5)) + 1e-9, f"{risk_pct:.2f}%",
         f"≤ {float(i.limits.get('max_risk_per_trade_pct', 1.5)):.1f}%", red_if_fail=True,
         note=f"Lỗ tối đa {max_loss:,.0f} đ nếu chạm cắt lỗ".replace(",", "."))
    bad = [f for f in (i.status_flags or []) if f in ("WARNING", "CONTROL", "RESTRICTED", "SUSPENDED")]
    item("STATUS", not bad, "Bình thường" if not bad else ", ".join(bad), "Không bị cảnh báo/kiểm soát", red_if_fail=True)
    rr = (tp - px) / (px - stop) if px > stop else 0
    item("RR", rr >= float(i.limits.get("min_risk_reward", 2.0)), f"1 : {rr:.1f}", f"≥ 1 : {float(i.limits.get('min_risk_reward', 2.0)):.0f}")
    pos_pct = (i.position_value + order_value) / equity * 100
    item("POSITION", pos_pct <= float(i.limits.get("max_position_pct", 20)), f"{pos_pct:.1f}%", f"≤ {float(i.limits.get('max_position_pct', 20)):.0f}%")
    sec_pct = (i.sector_value + order_value) / equity * 100
    item("SECTOR", sec_pct <= float(i.limits.get("max_sector_pct", 40)), f"{sec_pct:.1f}%", f"≤ {float(i.limits.get('max_sector_pct', 40)):.0f}%")
    ev_ok = i.earnings_in_days is None or i.earnings_in_days > 5
    item("EVENTS", ev_ok, "Không có" if ev_ok else f"BCTC/GDKHQ trong {i.earnings_in_days} phiên", "Không có trong 5 phiên")
    liq_ok = i.value_ma20 is None or order_value <= 0.10 * i.value_ma20
    item("LIQUIDITY", liq_ok, f"{order_value / i.value_ma20 * 100:.1f}% GTGD TB20" if i.value_ma20 else "—", "≤ 10% GTGD TB20")
    limit = i.chase_limits[0] if i.horizon == "SHORT" else i.chase_limits[1]
    chase = (i.gain_from_base_pct is not None and i.gain_from_base_pct > limit) or ((i.ceiling_streak or 0) >= 2)
    item("CHASE", not chase, f"Cách điểm phá nền {i.gain_from_base_pct:.0f}%" if i.gain_from_base_pct is not None else "—", f"≤ {limit}%")

    if i.guard_mode == "DEFENSIVE":
        result = "RED"
        items.insert(0, {"code": "GUARD", "name": "Cầu dao giới hạn lỗ", "level": "RED", "value": "Đang ở chế độ phòng thủ",
                         "limit": "Không mua mới", "note": None})
    else:
        levels = [it["level"] for it in items]
        result = "RED" if "RED" in levels else ("YELLOW" if "YELLOW" in levels else "GREEN")
    suggested = floor_lot(equity * float(i.limits.get("max_risk_per_trade_pct", 1.5)) / 100 / max(px - stop, 1))
    suggested = min(suggested, floor_lot(equity * float(i.limits.get("max_position_pct", 20)) / 100 / px))
    headline = {
        "GREEN": "Xanh: lệnh nằm trong mọi giới hạn của bạn.",
        "YELLOW": f"Vàng: {sum(1 for it in items if it['level'] == 'YELLOW')} điểm cần lưu ý. Có thể mua, nhưng nên giảm khối lượng.",
        "RED": "Đỏ: không nên mua lúc này. " + (
            "Đang ở chế độ phòng thủ." if i.guard_mode == "DEFENSIVE" else next((it["name"] + " không đạt." for it in items if it["level"] == "RED"), "")),
    }[result]
    return {
        "result": result,
        "headline": headline,
        "items": items,
        "order_value": order_value,
        "max_loss": max_loss,
        "risk_pct": round(risk_pct, 2),
        "risk_reward": round(rr, 2),
        "suggested_qty": int(suggested),
        "reliability": {"win_rate": i.reliability_pct, "samples": i.reliability_samples},
    }


# ---------------------------------------------------------------- guard (BR-15)
def guard_decision(mode: str, week_pnl_pct: float, month_pnl_pct: float, weekly_limit: float, monthly_limit: float,
                   today, release_at, is_new_month: bool) -> str | None:
    """Returns 'ON', 'OFF' or None (no change)."""
    if mode == "NORMAL" and (week_pnl_pct <= -weekly_limit or month_pnl_pct <= -monthly_limit):
        return "ON"
    if mode == "DEFENSIVE" and ((release_at and today >= release_at) or is_new_month):
        return "OFF"
    return None


# ---------------------------------------------------------------- margin & stress (4.6i)
def margin_metrics(positions: list[dict], cash: float, loan: float, call_ratio: float, force_ratio: float, shocks=(-10, -20, -30)) -> dict:
    mv = sum(p["quantity"] * p["price"] for p in positions)
    ratio = (mv + cash - loan) / mv if mv > 0 else None
    per_symbol = []
    for p in positions:
        if ratio is None or p["price"] <= 0:
            continue
        w = p["quantity"] * p["price"] / mv
        # price at which the account ratio hits call / force sell, assuming only this symbol moves
        def px_at(target):
            # (mv*(1-w) + q*x + cash - loan) / (mv*(1-w) + q*x) = target → solve x
            q = p["quantity"]
            other = mv * (1 - w)
            denom = q * (1 - target)
            if denom <= 0:
                return None
            x = (target * other - other - cash + loan) / denom
            return max(0.0, x)
        per_symbol.append({"symbol": p["symbol"], "weight_pct": round(w * 100, 1), "call_price": px_at(call_ratio), "force_price": px_at(force_ratio),
                           "beta": p.get("beta")})
    scenarios = []
    for s in shocks:
        mv_s = sum(p["quantity"] * p["price"] * (1 + (p.get("beta") or 1.0) * s / 100) for p in positions)
        r_s = (mv_s + cash - loan) / mv_s if mv_s > 0 else None
        need = max(0.0, call_ratio * mv_s - (mv_s + cash - loan)) if mv_s > 0 and loan > 0 else 0.0
        scenarios.append({"shock_pct": s, "market_value": round(mv_s), "equity": round(mv_s + cash - loan), "loss": round(mv_s - mv),
                          "margin_ratio": round(r_s, 3) if r_s is not None else None, "margin_call": bool(r_s is not None and r_s < call_ratio and loan > 0),
                          "cash_needed": round(need)})
    return {"market_value": round(mv), "cash": cash, "loan": loan, "equity": round(mv + cash - loan), "margin_ratio": round(ratio, 3) if ratio else None,
            "call_ratio": call_ratio, "force_ratio": force_ratio, "positions": per_symbol, "scenarios": scenarios}


# ---------------------------------------------------------------- correlation (4.6j)
def correlated_groups(returns: pd.DataFrame, weights: dict[str, float], rho: float = 0.8) -> tuple[list[dict], pd.DataFrame | None]:
    """returns: DataFrame (date × symbol) of daily returns over 60 sessions. weights: symbol → weight (0–100)."""
    cols = [c for c in returns.columns if returns[c].notna().sum() >= 30]
    if len(cols) < 2:
        return [], None
    R = returns[cols].corr()
    parent = {c: c for c in cols}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in cols:
        for b in cols:
            if a < b and R.loc[a, b] > rho:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for c in cols:
        groups.setdefault(find(c), []).append(c)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        pairs = [(a, b, R.loc[a, b]) for a in members for b in members if a < b]
        out.append({"symbols": sorted(members), "weight_pct": round(sum(weights.get(m, 0) for m in members), 1),
                    "avg_corr": round(float(np.mean([p[2] for p in pairs])), 2)})
    out.sort(key=lambda g: -g["weight_pct"])
    return out, R.round(2)


def beta(stock_returns: pd.Series, index_returns: pd.Series) -> float | None:
    df = pd.concat([stock_returns, index_returns], axis=1).dropna()
    if len(df) < 30:
        return None
    var = df.iloc[:, 1].var()
    if not var:
        return None
    return float(df.iloc[:, 0].cov(df.iloc[:, 1]) / var)


# ---------------------------------------------------------------- reliability (4.6k)
def reliability_label(win_rate: float | None, samples: int | None) -> tuple[bool, str | None]:
    """Returns (stand_aside, text). Shown only when ≥ 30 samples (BR-18)."""
    if win_rate is None or (samples or 0) < 30:
        return False, None
    return (win_rate < 50), f"đúng {win_rate:.0f}% ({samples} lần)"


def nan_to_none(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    return v
