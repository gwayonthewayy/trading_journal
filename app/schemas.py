from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BuyRequest(BaseModel):
    ticker: str
    market: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    fx_rate_to_base: Optional[float] = Field(default=None, gt=0)
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    fee: float = Field(default=0, ge=0)
    sl: Optional[float] = Field(default=None, ge=0)
    tp: Optional[float] = Field(default=None, ge=0)
    buy_reason: Optional[str] = None
    note: Optional[str] = None
    trade_group_id: Optional[int] = None
    trade_group_title: Optional[str] = None
    symbol_name: Optional[str] = None
    ts: Optional[datetime] = None


class SellAllocationIn(BaseModel):
    lot_id: int
    qty_sold: float = Field(gt=0)


class SellRequest(BaseModel):
    ticker: str
    market: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    fx_rate_to_base: Optional[float] = Field(default=None, gt=0)
    price: float = Field(gt=0)
    fee: float = Field(default=0, ge=0)
    reason: Optional[str] = None
    note: Optional[str] = None
    ts: Optional[datetime] = None
    trade_group_id: Optional[int] = None
    allocations: list[SellAllocationIn] = Field(min_length=1)


class LotSLUpdateRequest(BaseModel):
    lot_id: int
    new_sl: Optional[float] = Field(default=None, ge=0)
    new_tp: Optional[float] = Field(default=None, ge=0)
    reason: Optional[str] = None
    note: Optional[str] = None
    ts: Optional[datetime] = None


class CashflowRequest(BaseModel):
    cash_amount: float
    currency: Optional[str] = None
    fx_rate_to_base: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = None
    ts: Optional[datetime] = None


class ReviewRequest(BaseModel):
    trade_group_id: int
    review_text: str


class EventUpdateRequest(BaseModel):
    ticker: Optional[str] = None
    ts: Optional[datetime] = None
    market: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    fx_rate_to_base: Optional[float] = Field(default=None, gt=0)
    qty: Optional[float] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, ge=0)
    fee: Optional[float] = Field(default=None, ge=0)
    sl: Optional[float] = Field(default=None, ge=0)
    tp: Optional[float] = Field(default=None, ge=0)
    cash_amount: Optional[float] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    image_url: Optional[str] = None
    review_text: Optional[str] = None


class EventOut(BaseModel):
    id: int
    ts: datetime
    type: str
    ticker: Optional[str]
    market: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    fx_rate_to_base: float
    symbol_name: Optional[str]
    qty: Optional[float]
    price: Optional[float]
    fee: float
    sl: Optional[float]
    tp: Optional[float]
    amount: Optional[float]
    realized_pnl: Optional[float]
    realized_pnl_local: Optional[float]
    book_asset: float
    note: Optional[str]
    image_url: Optional[str]
    reason: Optional[str]
    review: Optional[str]
    open_risk: float = 0
    open_risk_delta: float = 0
    open_risk_delta_details: Optional[str] = None


class PortfolioLotOut(BaseModel):
    lot_id: int
    opened_at: datetime
    qty_open: float
    market: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    fx_rate_to_base: float
    entry_price: float
    sl: Optional[float]
    tp: Optional[float]
    buy_fee: float
    buy_reason: Optional[str]
    note: Optional[str]
    open_risk: float


class PortfolioRowOut(BaseModel):
    ticker: str
    market: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    symbol_name: Optional[str]
    qty_open: float
    avg_entry_price: float
    sl_tp: str
    amount_cost: float
    open_risk: float
    open_risk_pct: float
    lots: list[PortfolioLotOut]
