from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class EventType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
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
