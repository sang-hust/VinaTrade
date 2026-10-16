from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Industry(Base):
    """ICB sector codes (level 2 = sector group shown in app)."""

    __tablename__ = "industries"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_vi: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[int] = mapped_column(Integer, default=2)
    parent_code: Mapped[str | None] = mapped_column(String(8))


class Stock(Base):
    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8), index=True)  # HOSE | HNX | UPCOM
    name_vi: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    short_name: Mapped[str | None] = mapped_column(String(120))
    industry_code: Mapped[str | None] = mapped_column(ForeignKey("industries.code"), index=True)
    icb_lv4: Mapped[str | None] = mapped_column(String(8))
    listed_shares: Mapped[int | None] = mapped_column(BigInteger)
    free_float_pct: Mapped[float | None] = mapped_column(Float)
    foreign_pct: Mapped[float | None] = mapped_column(Float)
    state_pct: Mapped[float | None] = mapped_column(Float)
    listing_date: Mapped[date | None] = mapped_column(Date)
    is_bank: Mapped[bool] = mapped_column(Boolean, default=False)
    in_vn30: Mapped[bool] = mapped_column(Boolean, default=False)
    status_flags: Mapped[list | None] = mapped_column(JSON)  # ["WARNING","CONTROL","RESTRICTED"]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    profile_vi: Mapped[str | None] = mapped_column(Text)
    source_meta: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PriceDaily(Base):
    """Adjusted daily OHLCV. Prices in VND (float because adjusted prices can be fractional)."""

    __tablename__ = "price_daily"
    __table_args__ = (Index("ix_price_daily_date", "trade_date"),)

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float)  # VND traded value
    source: Mapped[str | None] = mapped_column(String(12))


class PriceIntraday(Base):
    __tablename__ = "price_intraday"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)


class IndexDaily(Base):
    __tablename__ = "index_daily"

    index_code: Mapped[str] = mapped_column(String(16), primary_key=True)  # VNINDEX | VN30 | HNXINDEX | UPCOMINDEX
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float)
    advances: Mapped[int | None] = mapped_column(Integer)
    declines: Mapped[int | None] = mapped_column(Integer)
    unchanged: Mapped[int | None] = mapped_column(Integer)
    pct_above_ma50: Mapped[float | None] = mapped_column(Float)
    pct_above_ma200: Mapped[float | None] = mapped_column(Float)


class FinancialStatement(Base):
    """One row per (symbol, year, quarter). quarter=5 means full year (Vietcap convention)."""

    __tablename__ = "financial_statements"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarter: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_date: Mapped[date | None] = mapped_column(Date)
    revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    operating_profit: Mapped[float | None] = mapped_column(Float)
    pretax_profit: Mapped[float | None] = mapped_column(Float)
    net_profit: Mapped[float | None] = mapped_column(Float)  # attributable to parent
    eps: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    total_liabilities: Mapped[float | None] = mapped_column(Float)
    current_liabilities: Mapped[float | None] = mapped_column(Float)
    current_assets: Mapped[float | None] = mapped_column(Float)
    equity: Mapped[float | None] = mapped_column(Float)
    short_debt: Mapped[float | None] = mapped_column(Float)
    long_debt: Mapped[float | None] = mapped_column(Float)
    cash: Mapped[float | None] = mapped_column(Float)
    receivables: Mapped[float | None] = mapped_column(Float)
    inventory: Mapped[float | None] = mapped_column(Float)
    cfo: Mapped[float | None] = mapped_column(Float)  # operating cash flow
    capex: Mapped[float | None] = mapped_column(Float)
    dividends_paid: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(12))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinancialRatio(Base):
    """TTM ratios recomputed daily from statements + price (spec: financial_ratios + valuation_daily merged)."""

    __tablename__ = "financial_ratios"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    eps_ttm: Mapped[float | None] = mapped_column(Float)
    bvps: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ps: Mapped[float | None] = mapped_column(Float)
    peg: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    roa: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)
    debt_to_equity: Mapped[float | None] = mapped_column(Float)
    current_ratio: Mapped[float | None] = mapped_column(Float)
    revenue_yoy: Mapped[float | None] = mapped_column(Float)  # latest quarter vs same quarter last year, %
    profit_yoy: Mapped[float | None] = mapped_column(Float)
    revenue_cagr_3y: Mapped[float | None] = mapped_column(Float)
    profit_cagr_3y: Mapped[float | None] = mapped_column(Float)
    cfo_to_profit: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    fair_value: Mapped[float | None] = mapped_column(Float)
    fair_value_pe: Mapped[float | None] = mapped_column(Float)
    fair_value_pb: Mapped[float | None] = mapped_column(Float)
    fair_value_graham: Mapped[float | None] = mapped_column(Float)
    margin_of_safety: Mapped[float | None] = mapped_column(Float)
    latest_year: Mapped[int | None] = mapped_column(Integer)
    latest_quarter: Mapped[int | None] = mapped_column(Integer)
    cfo_negative_quarters: Mapped[int | None] = mapped_column(Integer)
    receivable_gap_pt: Mapped[float | None] = mapped_column(Float)
    inventory_gap_pt: Mapped[float | None] = mapped_column(Float)
    dilution_pct: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CorporateAction(Base):
    """Corporate events from VNDirect (investorRight + stockAlert). ex_date = ngày GDKHQ (effectiveDate)."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    # CASH_DIVIDEND | STOCK_DIVIDEND | BONUS | ISSUE | AGM | AGM_RECORD | POLL | LISTED | PAY_DATE_CHANGE
    # ALERT_CONTROL | ALERT_SPECIAL_CONTROL | ALERT_WARNING | ALERT_SUSPEND | ALERT_DELIST | ALERT_NOTICE | ALERT_OTHER
    ex_date: Mapped[date | None] = mapped_column(Date, index=True)
    record_date: Mapped[date | None] = mapped_column(Date)
    event_date: Mapped[date | None] = mapped_column(Date)  # pay date / meeting date
    disclosure_date: Mapped[date | None] = mapped_column(Date, index=True)
    ratio: Mapped[float | None] = mapped_column(Float)  # % (10 = 10%)
    cash_per_share: Mapped[float | None] = mapped_column(Float)
    issue_price: Mapped[float | None] = mapped_column(Float)
    shares: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(12))


class InsiderTransaction(Base):
    """Director / major-holder / related-person deals (Vietcap). side BUY | SELL; status REGISTERED | DONE | CANCELLED."""

    __tablename__ = "insider_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    person: Mapped[str | None] = mapped_column(String(255))
    relation: Mapped[str | None] = mapped_column(String(255))  # chức vụ / quan hệ
    related_person: Mapped[str | None] = mapped_column(String(255))
    event_code: Mapped[str | None] = mapped_column(String(12))  # DDIND cá nhân | DDINS tổ chức | DDRP người liên quan
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int | None] = mapped_column(BigInteger)  # registered
    quantity_done: Mapped[int | None] = mapped_column(BigInteger)
    shares_before: Mapped[int | None] = mapped_column(BigInteger)
    shares_after: Mapped[int | None] = mapped_column(BigInteger)
    ownership_after_pct: Mapped[float | None] = mapped_column(Float)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    announce_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(12))


class InvestorFlow(Base):
    """Foreign (VNDirect / SSI) and proprietary (VNDirect) trading per symbol per day, VND."""

    __tablename__ = "investor_flows"
    __table_args__ = (Index("ix_investor_flows_date", "trade_date"),)

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    foreign_buy_val: Mapped[float | None] = mapped_column(Float)
    foreign_sell_val: Mapped[float | None] = mapped_column(Float)
    foreign_net_val: Mapped[float | None] = mapped_column(Float)
    foreign_buy_vol: Mapped[float | None] = mapped_column(Float)
    foreign_sell_vol: Mapped[float | None] = mapped_column(Float)
    foreign_net_vol: Mapped[float | None] = mapped_column(Float)
    foreign_room: Mapped[float | None] = mapped_column(Float)
    prop_buy_val: Mapped[float | None] = mapped_column(Float)
    prop_sell_val: Mapped[float | None] = mapped_column(Float)
    prop_net_val: Mapped[float | None] = mapped_column(Float)


class BrokerRecommendation(Base):
    __tablename__ = "broker_recommendations"
    __table_args__ = (UniqueConstraint("symbol", "firm", "report_date", name="uq_broker_rec"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    firm: Mapped[str] = mapped_column(String(80))
    rec_type: Mapped[str | None] = mapped_column(String(16))  # BUY | OUTPERFORM | HOLD | NEUTRAL | UNDERPERFORM | SELL
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_price: Mapped[float | None] = mapped_column(Float)  # VND
    target_price: Mapped[float | None] = mapped_column(Float)  # VND
    analyst: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(String(40))


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (Index("ix_news_published", "published_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    source: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbols: Mapped[list | None] = mapped_column(JSON)
    is_market: Mapped[bool] = mapped_column(Boolean, default=False)
    sentiment: Mapped[float | None] = mapped_column(Float)  # −1..1
    sentiment_label: Mapped[str | None] = mapped_column(String(12))  # POSITIVE | NEUTRAL | NEGATIVE
    ai_summary: Mapped[str | None] = mapped_column(String(400))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsStockLink(Base):
    __tablename__ = "news_stock_links"

    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), primary_key=True, index=True)
