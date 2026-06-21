from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class EventType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    SL_UPDATE = "SL_UPDATE"
    CASHFLOW = "CASHFLOW"
    REVIEW = "REVIEW"


class Symbol(SQLModel, table=True):
    ticker: str = Field(primary_key=True, max_length=20)
    name: Optional[str] = Field(default=None, max_length=200)
    asset_type: Optional[str] = Field(default="EQUITY", max_length=50)
    market: Optional[str] = Field(default=None, max_length=16)
    exchange: Optional[str] = Field(default=None, max_length=32)
    currency: Optional[str] = Field(default=None, max_length=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TradeGroup(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    tags: Optional[str] = Field(default=None, max_length=255)
    note: Optional[str] = Field(default=None)
    review: Optional[str] = Field(default=None)
    setup_type: Optional[str] = Field(default=None, max_length=80)
    planned_entry: Optional[float] = Field(default=None, ge=0)
    planned_stop: Optional[float] = Field(default=None, ge=0)
    planned_risk_pct: Optional[float] = Field(default=None, ge=0)
    realized_r: Optional[float] = Field(default=None)
    rule_compliance: Optional[str] = Field(default=None, max_length=80)
    mistake_tag: Optional[str] = Field(default=None, max_length=120)
    minervini_checklist: Optional[str] = Field(default=None)
    candidate_id: Optional[str] = Field(default=None, max_length=140, index=True)
    scan_date: Optional[date] = Field(default=None)
    trade_status: Optional[str] = Field(default="candidate", max_length=32)
    pivot_price: Optional[float] = Field(default=None, ge=0)
    buy_zone_low: Optional[float] = Field(default=None, ge=0)
    buy_zone_high: Optional[float] = Field(default=None, ge=0)
    invalidation_price: Optional[float] = Field(default=None, ge=0)
    overlay_snapshot_json: Optional[str] = Field(default=None)
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = Field(default=None)


class Lot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbol.ticker", max_length=20)
    market: Optional[str] = Field(default=None, max_length=16)
    exchange: Optional[str] = Field(default=None, max_length=32)
    currency: Optional[str] = Field(default=None, max_length=10)
    fx_rate_to_base: float = Field(default=1.0, gt=0)
    trade_group_id: Optional[int] = Field(default=None, foreign_key="tradegroup.id")
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    qty_open: float = Field(default=0, ge=0)
    entry_price: float = Field(ge=0)
    buy_fee: float = Field(default=0, ge=0)
    sl: Optional[float] = Field(default=None, ge=0)
    tp: Optional[float] = Field(default=None, ge=0)
    buy_reason: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None)


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    type: EventType

    ticker: Optional[str] = Field(default=None, foreign_key="symbol.ticker", max_length=20)
    market: Optional[str] = Field(default=None, max_length=16)
    exchange: Optional[str] = Field(default=None, max_length=32)
    currency: Optional[str] = Field(default=None, max_length=10)
    fx_rate_to_base: float = Field(default=1.0, gt=0)
    trade_group_id: Optional[int] = Field(default=None, foreign_key="tradegroup.id")
    lot_id: Optional[int] = Field(default=None, foreign_key="lot.id")

    qty: Optional[float] = Field(default=None, ge=0)
    price: Optional[float] = Field(default=None, ge=0)
    fee: float = Field(default=0, ge=0)

    sl: Optional[float] = Field(default=None)
    tp: Optional[float] = Field(default=None)

    cash_amount: Optional[float] = Field(default=None)
    reason: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None)
    image_url: Optional[str] = Field(default=None)
    review_text: Optional[str] = Field(default=None)

    realized_pnl: Optional[float] = Field(default=None)
    realized_pnl_local: Optional[float] = Field(default=None)
    source_broker: Optional[str] = Field(default=None, max_length=20, index=True)
    external_execution_id: Optional[str] = Field(default=None, max_length=160, index=True)


class SellAllocation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sell_event_id: int = Field(foreign_key="event.id")
    lot_id: int = Field(foreign_key="lot.id")
    qty_sold: float = Field(gt=0)


class Setting(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    base_currency: str = Field(default="KRW", max_length=10)
    risk_denominator: str = Field(default="BOOK_ASSET", max_length=50)
    est_exit_fee_rate: float = Field(default=0, ge=0)


class BrokerExecution(SQLModel, table=True):
    execution_key: str = Field(primary_key=True, max_length=64)
    broker: str = Field(default="KIS", max_length=20, index=True)
    account_hash: str = Field(max_length=32, index=True)
    environment: str = Field(default="paper", max_length=16)
    trade_date: date = Field(index=True)
    order_no: str = Field(max_length=40, index=True)
    ticker: str = Field(max_length=20, index=True)
    symbol_name: Optional[str] = Field(default=None, max_length=200)
    side: str = Field(max_length=8)
    market: str = Field(max_length=16)
    exchange: str = Field(max_length=32)
    currency: str = Field(max_length=10)
    executed_at: datetime
    observed_qty: float = Field(default=0, ge=0)
    observed_avg_price: float = Field(default=0, ge=0)
    observed_fee: float = Field(default=0, ge=0)
    observed_tax: float = Field(default=0, ge=0)
    applied_qty: float = Field(default=0, ge=0)
    applied_notional: float = Field(default=0, ge=0)
    applied_fee: float = Field(default=0, ge=0)
    applied_tax: float = Field(default=0, ge=0)
    processing_status: str = Field(default="observed", max_length=40, index=True)
    last_error: Optional[str] = Field(default=None)
    event_ids_json: Optional[str] = Field(default=None)
    raw_payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrokerSyncState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    broker: str = Field(default="KIS", max_length=20)
    environment: str = Field(default="paper", max_length=16)
    paused: bool = Field(default=False)
    websocket_status: str = Field(default="disabled", max_length=32)
    rest_status: str = Field(default="idle", max_length=32)
    last_started_at: Optional[datetime] = Field(default=None)
    last_success_at: Optional[datetime] = Field(default=None)
    last_error_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    last_query_start: Optional[date] = Field(default=None)
    last_query_end: Optional[date] = Field(default=None)
    token_status: str = Field(default="not_requested", max_length=32)
    new_count: int = Field(default=0, ge=0)
    duplicate_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
