from __future__ import annotations

import csv
import html
import json
import math
import re
import shutil
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from sqlmodel import Session, select

from app.database import DB_PATH
from app.models import Event, EventType, Lot, SellAllocation, Setting, Symbol, TradeGroup
from app.schemas import (
    BuyRequest,
    CashflowRequest,
    DuplicateCheckRequest,
    EventUpdateRequest,
    LotSLUpdateRequest,
    ReviewRequest,
    SellRequest,
)

BACKUP_DIR = Path("data/backups")
UPLOAD_DIR = Path("data/uploads")
MAX_BACKUPS = 200
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
BENCHMARK_SYMBOLS = ("SPY", "QQQ", "IWM", "FFTY", "KOSPI", "KOSDAQ")
BENCHMARK_YF_SYMBOL_MAP = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "FFTY": "FFTY",
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
}
BENCHMARK_CACHE_TTL_SECONDS = 60 * 60 * 6
FX_CACHE_TTL_SECONDS = 60 * 30
QUOTE_CACHE_TTL_SECONDS = 60 * 5
NAME_CACHE_TTL_SECONDS = 60 * 60 * 24
DAILY_HIGH_CACHE_TTL_SECONDS = 60 * 60 * 6
WIN_RATE_BREAKEVEN_EPSILON_USD = 10.0
RETURN_DENOMINATOR_MIN_BASE = 100.0
DUPLICATE_TS_WINDOW_SECONDS = 5 * 60
DUPLICATE_SCAN_DAYS = 30
MONTHLY_CHECK_START_MONTH = date(2025, 1, 1)
BREAKEVEN_REASON_PATTERNS = (
    re.compile(r"\bbe\b", re.IGNORECASE),
    re.compile(r"break[\s_-]?even", re.IGNORECASE),
    re.compile(r"breakeven", re.IGNORECASE),
    re.compile(r"蹂몄젅", re.IGNORECASE),
    re.compile(r"蹂몄쟾", re.IGNORECASE),
)
_benchmark_cache: dict[str, dict[str, Any]] = {}
_fx_cache: dict[str, dict[str, Any]] = {}
_quote_cache: dict[str, dict[str, Any]] = {}
_name_cache: dict[str, dict[str, Any]] = {}
_daily_high_cache: dict[str, dict[str, Any]] = {}

MONTHLY_CHECK_METRICS: list[dict[str, str]] = [
    {"key": "trade_count", "label": "Trades", "format": "count"},
    {"key": "avg_profit_pct", "label": "Avg Profit", "format": "pct"},
    {"key": "avg_loss_pct", "label": "Avg Loss", "format": "pct"},
    {"key": "win_rate_pct", "label": "Win Rate", "format": "pct"},
    {"key": "success_failure_ratio", "label": "Success/Failure", "format": "ratio"},
    {"key": "adjusted_success_failure_ratio", "label": "Adj. Success/Failure", "format": "ratio"},
    {"key": "max_profit_pct", "label": "Max Profit", "format": "pct"},
    {"key": "max_loss_pct", "label": "Max Loss", "format": "pct"},
    {"key": "avg_win_hold_days", "label": "Avg Win Hold Days", "format": "days"},
    {"key": "avg_loss_hold_days", "label": "Avg Loss Hold Days", "format": "days"},
]


def _normalize_hk_ticker(value: str) -> str:
    raw = (value or "").strip().upper()
    if raw.endswith(".HK"):
        raw = raw[:-3]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        if len(digits) <= 5:
            return digits.zfill(5)
        return digits
    return (value or "").strip().upper()


def normalize_ticker(ticker: str, market: str | None = None) -> str:
    value = ticker.strip().upper()
    if not value:
        raise HTTPException(status_code=400, detail="ticker is required")
    if _normalize_upper_optional(market) == "HK":
        return _normalize_hk_ticker(value)
    return value


def _normalize_upper_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped.upper() if stripped else None


def _normalize_optional_ts(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _split_image_urls(value: str | None) -> list[str]:
    if value is None:
        return []
    urls: list[str] = []
    for line in value.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate in urls:
            continue
        urls.append(candidate)
    return urls


def _parse_event_type(value: str | None) -> EventType:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="event_type is required")
    try:
        return EventType(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid event_type") from exc


def _numbers_almost_equal(left: float | None, right: float | None, eps: float = 1e-9) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= eps


def _get_base_currency(session: Session) -> str:
    settings = session.get(Setting, 1)
    if settings and settings.base_currency and settings.base_currency.strip():
        return settings.base_currency.strip().upper()
    return "USD"


def _parse_fx_rate_value(raw_rate: Any) -> float:
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid FX rate value") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("invalid FX rate value")
    return rate


def _fetch_fx_rate_from_frankfurter(from_currency: str, to_currency: str, fx_date: date | None = None) -> float:
    if fx_date:
        url = f"https://api.frankfurter.app/{fx_date.isoformat()}?from={from_currency}&to={to_currency}"
    else:
        url = f"https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}"
    with urlopen(url, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict) or to_currency not in rates:
        raise ValueError("invalid FX provider response")
    return _parse_fx_rate_value(rates[to_currency])


def _fetch_fx_rate_from_open_er_api(from_currency: str, to_currency: str) -> float:
    url = f"https://open.er-api.com/v6/latest/{from_currency}"
    with urlopen(url, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict) or to_currency not in rates:
        raise ValueError("invalid FX provider response")
    return _parse_fx_rate_value(rates[to_currency])


def _fetch_fx_rate_from_api(from_currency: str, to_currency: str, fx_date: date | None = None) -> float:
    key_date = fx_date.isoformat() if fx_date else "latest"
    cache_key = f"{from_currency}:{to_currency}:{key_date}"
    now_ts = datetime.utcnow().timestamp()
    cached = _fx_cache.get(cache_key)
    if cached and now_ts - cached["fetched_at"] < FX_CACHE_TTL_SECONDS:
        return cached["rate"]

    attempts: list[tuple[str, Any]] = []
    candidates: list[tuple[str, Any]] = []
    candidates.append(("frankfurter", lambda: _fetch_fx_rate_from_frankfurter(from_currency, to_currency, fx_date)))
    if fx_date is not None:
        candidates.append(("frankfurter-latest", lambda: _fetch_fx_rate_from_frankfurter(from_currency, to_currency, None)))
    candidates.append(("open-er-api", lambda: _fetch_fx_rate_from_open_er_api(from_currency, to_currency)))

    rate: float | None = None
    for provider_name, provider_call in candidates:
        try:
            rate = provider_call()
            break
        except (URLError, TimeoutError, ValueError) as exc:
            attempts.append((provider_name, exc))

    if rate is None:
        raise HTTPException(
            status_code=502,
            detail="failed to fetch FX rate automatically; set fx_rate_to_base manually",
        )

    _fx_cache[cache_key] = {"fetched_at": now_ts, "rate": rate}
    return rate


def _resolve_fx_rate_to_base(
    base_currency: str,
    currency: str | None,
    fx_rate_to_base: float | None,
    fx_date: date | None = None,
) -> float:
    normalized_currency = _normalize_upper_optional(currency) or base_currency
    if normalized_currency == base_currency:
        return 1.0
    if fx_rate_to_base is not None and fx_rate_to_base > 0:
        return fx_rate_to_base
    return _fetch_fx_rate_from_api(normalized_currency, base_currency, fx_date)


def _to_base(amount_local: float | None, fx_rate_to_base: float | None) -> float:
    if amount_local is None:
        return 0.0
    fx = fx_rate_to_base if (fx_rate_to_base is not None and fx_rate_to_base > 0) else 1.0
    return amount_local * fx


def _currency_symbol(currency: str | None) -> str:
    normalized = _normalize_upper_optional(currency)
    if normalized == "USD":
        return "$"
    if normalized == "KRW":
        return "₩"
    if normalized == "HKD":
        return "HK$"
    if normalized:
        return f"{normalized} "
    return ""


def _trim_decimal_text(text: str) -> str:
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _format_number_with_commas(value: float | int, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    return f"{number:,.{max(0, decimals)}f}"


def _format_price_for_display(value: float | None) -> str:
    if value is None:
        return ""
    abs_value = abs(value)
    if abs_value >= 1000:
        return _trim_decimal_text(_format_number_with_commas(value, 2))
    if abs_value >= 1:
        return _trim_decimal_text(_format_number_with_commas(value, 4))
    return _trim_decimal_text(_format_number_with_commas(value, 6))


def _format_sl_tp_value(value: float | None) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    abs_value = abs(number)
    if abs_value >= 1000:
        scaled = number / 1000.0
        if abs(scaled) >= 100:
            return f"{scaled:,.0f}K"
        if abs(scaled) >= 10:
            return f"{_trim_decimal_text(f'{scaled:,.1f}')}K"
        return f"{_trim_decimal_text(f'{scaled:,.2f}')}K"
    return _trim_decimal_text(_format_number_with_commas(number, 2 if abs_value >= 1 else 4))


def _convert_currency_amount(
    amount: float | None,
    from_currency: str | None,
    to_currency: str | None,
    fx_date: date | None = None,
) -> float | None:
    if amount is None:
        return None
    source = _normalize_upper_optional(from_currency)
    target = _normalize_upper_optional(to_currency)
    if not source or not target:
        return None
    if source == target:
        return float(amount)
    try:
        rate = _fetch_fx_rate_from_api(source, target, fx_date=fx_date)
    except HTTPException:
        return None
    except Exception:
        return None
    return float(amount) * rate


def _dual_currency_from_base(amount: float, base_currency: str) -> dict[str, float | None]:
    return {
        "usd": _convert_currency_amount(amount, base_currency, "USD"),
        "krw": _convert_currency_amount(amount, base_currency, "KRW"),
    }


def _is_breakeven_sell(realized_pnl: float, reason: str | None) -> bool:
    reason_text = (reason or "").strip()
    if reason_text:
        for pattern in BREAKEVEN_REASON_PATTERNS:
            if pattern.search(reason_text):
                return True
    return abs(realized_pnl) <= WIN_RATE_BREAKEVEN_EPSILON_USD


def _resolve_trade_group(
    session: Session,
    trade_group_id: int | None,
    trade_group_title: str | None,
    opened_at: datetime | None = None,
) -> int | None:
    if trade_group_id is not None:
        group = session.get(TradeGroup, trade_group_id)
        if group is None:
            raise HTTPException(status_code=400, detail="trade_group_id does not exist")
        return group.id

    title = (trade_group_title or "").strip()
    if not title:
        return None

    group = TradeGroup(title=title)
    if opened_at is not None:
        group.opened_at = opened_at
    session.add(group)
    session.flush()
    return group.id


def _ensure_symbol(
    session: Session,
    ticker: str,
    symbol_name: str | None = None,
    market: str | None = None,
    exchange: str | None = None,
    currency: str | None = None,
) -> None:
    symbol = session.get(Symbol, ticker)
    now = datetime.utcnow()
    normalized_market = _normalize_upper_optional(market)
    normalized_exchange = _normalize_upper_optional(exchange)
    normalized_currency = _normalize_upper_optional(currency)
    explicit_name = _normalize_optional_text(symbol_name)
    resolved_name = explicit_name or _get_symbol_name_from_yahoo(ticker, normalized_market)

    if symbol is None:
        session.add(
            Symbol(
                ticker=ticker,
                name=resolved_name or ticker,
                market=normalized_market,
                exchange=normalized_exchange,
                currency=normalized_currency,
                updated_at=now,
            )
        )
        return

    if explicit_name and symbol.name != explicit_name:
        symbol.name = explicit_name
    elif resolved_name and ((symbol.name or "").strip() in ("", ticker)):
        symbol.name = resolved_name
    if normalized_market:
        symbol.market = normalized_market
    if normalized_exchange:
        symbol.exchange = normalized_exchange
    if normalized_currency:
        symbol.currency = normalized_currency
    symbol.updated_at = now
    session.add(symbol)


def _build_lot_states_from_events(
    session: Session,
    up_to_ts: datetime | None = None,
    stop_before_event_id: int | None = None,
) -> dict[int, dict[str, Any]]:
    events = session.exec(select(Event).order_by(Event.ts.asc(), Event.id.asc())).all()

    sell_event_ids = [event.id for event in events if event.type == EventType.SELL and event.id is not None]
    sell_alloc_map = _build_sell_alloc_map(session, [x for x in sell_event_ids if x is not None])

    lot_states: dict[int, dict[str, Any]] = {}

    for event in events:
        if stop_before_event_id is not None and event.id == stop_before_event_id:
            break
        if up_to_ts is not None and event.ts > up_to_ts:
            break

        if event.type == EventType.BUY and event.lot_id is not None:
            lot_states[event.lot_id] = {
                "ticker": event.ticker,
                "entry_price": event.price or 0.0,
                "qty_open": event.qty or 0.0,
                "sl": event.sl,
                "tp": event.tp,
                "market": event.market,
                "exchange": event.exchange,
                "currency": event.currency,
                "fx_rate_to_base": event.fx_rate_to_base or 1.0,
            }
            continue

        if event.type == EventType.SELL and event.id is not None:
            for alloc in sell_alloc_map.get(event.id, []):
                lot_state = lot_states.get(alloc.lot_id)
                if lot_state is None:
                    continue
                lot_state["qty_open"] -= alloc.qty_sold
            continue

        if event.type == EventType.SL_UPDATE and event.lot_id is not None:
            lot_state = lot_states.get(event.lot_id)
            if lot_state is None:
                continue
            lot_state["sl"] = event.sl
            lot_state["tp"] = event.tp

    return lot_states


def _build_lot_states_before_event(session: Session, event_id: int) -> dict[int, dict[str, Any]]:
    return _build_lot_states_from_events(session, stop_before_event_id=event_id)


def _assert_non_negative_lot_states(session: Session) -> None:
    events = session.exec(select(Event).order_by(Event.ts.asc(), Event.id.asc())).all()
    sell_event_ids = [event.id for event in events if event.type == EventType.SELL and event.id is not None]
    sell_alloc_map = _build_sell_alloc_map(session, [x for x in sell_event_ids if x is not None])

    lot_qty: dict[int, float] = {}
    for event in events:
        if event.type == EventType.BUY and event.lot_id is not None:
            lot_qty[event.lot_id] = event.qty or 0.0
            continue

        if event.type == EventType.SELL and event.id is not None:
            for alloc in sell_alloc_map.get(event.id, []):
                current = lot_qty.get(alloc.lot_id)
                if current is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"allocation references unknown lot {alloc.lot_id}",
                    )
                next_qty = current - alloc.qty_sold
                if next_qty < -1e-9:
                    raise HTTPException(
                        status_code=400,
                        detail=f"historical allocation exceeds open qty for lot {alloc.lot_id}",
                    )
                lot_qty[alloc.lot_id] = max(0.0, next_qty)


def _sync_lot_snapshots_from_events(session: Session) -> None:
    lot_states = _build_lot_states_from_events(session)
    lots = session.exec(select(Lot)).all()

    for lot in lots:
        if lot.id is None:
            continue
        state = lot_states.get(lot.id)
        if state is None:
            lot.qty_open = 0.0
        else:
            lot.qty_open = max(0.0, state["qty_open"])
            lot.sl = state["sl"]
            lot.tp = state["tp"]
        session.add(lot)

    session.flush()


def create_buy(session: Session, req: BuyRequest) -> dict[str, Any]:
    market = _normalize_upper_optional(req.market)
    ticker = normalize_ticker(req.ticker, market)
    event_ts = _normalize_optional_ts(req.ts)
    base_currency = _get_base_currency(session)
    exchange = _normalize_upper_optional(req.exchange)
    currency = _normalize_upper_optional(req.currency) or base_currency
    fx_rate_to_base = _resolve_fx_rate_to_base(
        base_currency,
        currency,
        req.fx_rate_to_base,
        fx_date=event_ts.date() if event_ts else None,
    )

    _ensure_symbol(
        session,
        ticker,
        req.symbol_name,
        market=market,
        exchange=exchange,
        currency=currency,
    )
    trade_group_id = _resolve_trade_group(
        session,
        trade_group_id=req.trade_group_id,
        trade_group_title=req.trade_group_title,
        opened_at=event_ts,
    )

    lot = Lot(
        ticker=ticker,
        market=market,
        exchange=exchange,
        currency=currency,
        fx_rate_to_base=fx_rate_to_base,
        trade_group_id=trade_group_id,
        qty_open=req.qty,
        entry_price=req.price,
        buy_fee=req.fee,
        sl=req.sl,
        tp=req.tp,
        buy_reason=req.buy_reason,
        note=req.note,
    )
    if event_ts is not None:
        lot.opened_at = event_ts
    session.add(lot)
    session.flush()

    event = Event(
        type=EventType.BUY,
        ticker=ticker,
        market=market,
        exchange=exchange,
        currency=currency,
        fx_rate_to_base=fx_rate_to_base,
        trade_group_id=trade_group_id,
        lot_id=lot.id,
        qty=req.qty,
        price=req.price,
        fee=req.fee,
        sl=req.sl,
        tp=req.tp,
        reason=req.buy_reason,
        note=req.note,
    )
    if event_ts is not None:
        event.ts = event_ts
    session.add(event)
    session.flush()
    _sync_lot_snapshots_from_events(session)

    return {"lot_id": lot.id, "event_id": event.id}


def _compute_realized_pnl_from_allocations(
    alloc_by_lot: dict[int, float],
    state_at_sell: dict[int, dict[str, Any]],
    sell_price: float,
    sell_fee: float,
) -> float:
    sell_qty = 0.0
    allocated_cost = 0.0
    for lot_id, qty_sold in alloc_by_lot.items():
        lot_state = state_at_sell.get(lot_id)
        if lot_state is None:
            raise HTTPException(status_code=400, detail=f"missing historical lot state for lot {lot_id}")
        sell_qty += qty_sold
        allocated_cost += (lot_state.get("entry_price", 0.0) or 0.0) * qty_sold

    gross_sell = sell_price * sell_qty
    return gross_sell - allocated_cost - sell_fee


def create_sell(session: Session, req: SellRequest) -> dict[str, Any]:
    requested_market = _normalize_upper_optional(req.market)
    ticker = normalize_ticker(req.ticker, requested_market)
    event_ts = _normalize_optional_ts(req.ts)
    effective_ts = event_ts or datetime.utcnow()
    base_currency = _get_base_currency(session)

    requested_trade_group_id = req.trade_group_id
    if requested_trade_group_id is not None:
        group = session.get(TradeGroup, requested_trade_group_id)
        if group is None:
            raise HTTPException(status_code=400, detail="trade_group_id does not exist")

    alloc_by_lot: dict[int, float] = defaultdict(float)
    for alloc in req.allocations:
        alloc_by_lot[alloc.lot_id] += alloc.qty_sold

    lot_ids = list(alloc_by_lot.keys())
    lots = session.exec(select(Lot).where(Lot.id.in_(lot_ids))).all()
    if len(lots) != len(lot_ids):
        raise HTTPException(status_code=400, detail="one or more lots do not exist")

    if requested_market is None:
        inferred_markets = {
            m for m in (_normalize_upper_optional(lot.market) for lot in lots) if m is not None
        }
        if len(inferred_markets) == 1:
            ticker = normalize_ticker(ticker, next(iter(inferred_markets)))

    lot_trade_groups = {lot.trade_group_id for lot in lots}
    if len(lot_trade_groups) > 1:
        raise HTTPException(
            status_code=400,
            detail="allocation lots must have same trade_group_id",
        )
    inferred_trade_group_id = next(iter(lot_trade_groups)) if lot_trade_groups else None
    if (
        requested_trade_group_id is not None
        and inferred_trade_group_id is not None
        and requested_trade_group_id != inferred_trade_group_id
    ):
        raise HTTPException(
            status_code=400,
            detail="sell trade_group_id must match allocated BUY lot trade_group_id",
        )
    effective_trade_group_id = (
        inferred_trade_group_id if inferred_trade_group_id is not None else requested_trade_group_id
    )

    lot_map = {lot.id: lot for lot in lots}
    state_at_sell = _build_lot_states_from_events(session, up_to_ts=effective_ts)

    for lot_id, qty_sold in alloc_by_lot.items():
        lot = lot_map[lot_id]
        if lot.ticker != ticker:
            raise HTTPException(status_code=400, detail="allocation includes different ticker lot")
        state = state_at_sell.get(lot_id)
        open_qty = state["qty_open"] if state is not None else 0.0
        if qty_sold > open_qty + 1e-9:
            raise HTTPException(status_code=400, detail=f"allocation exceeds open qty for lot {lot_id}")

    open_lots = [
        state for state in state_at_sell.values() if state.get("ticker") == ticker and state.get("qty_open", 0) > 0
    ]
    total_open_qty = sum(state["qty_open"] for state in open_lots)
    if total_open_qty <= 0:
        raise HTTPException(status_code=400, detail="no open position for ticker")

    sell_qty = sum(alloc_by_lot.values())
    if sell_qty > total_open_qty:
        raise HTTPException(status_code=400, detail="allocation sum exceeds open qty")

    first_lot_state = state_at_sell.get(lot_ids[0])
    if first_lot_state is None:
        raise HTTPException(status_code=400, detail="missing historical lot state")

    market = _normalize_upper_optional(req.market) or _normalize_upper_optional(first_lot_state.get("market"))
    exchange = _normalize_upper_optional(req.exchange) or _normalize_upper_optional(first_lot_state.get("exchange"))
    currency = _normalize_upper_optional(req.currency) or _normalize_upper_optional(first_lot_state.get("currency")) or base_currency
    inferred_fx = first_lot_state.get("fx_rate_to_base")
    fx_rate_to_base = _resolve_fx_rate_to_base(
        base_currency,
        currency,
        req.fx_rate_to_base or inferred_fx,
        fx_date=effective_ts.date(),
    )

    for lot_id in lot_ids:
        state = state_at_sell.get(lot_id)
        if state is None:
            raise HTTPException(status_code=400, detail=f"missing historical lot state for lot {lot_id}")
        state_market = _normalize_upper_optional(state.get("market"))
        state_exchange = _normalize_upper_optional(state.get("exchange"))
        if market and state_market not in (None, market):
            raise HTTPException(status_code=400, detail="allocation lots must have same market")
        if exchange and state_exchange not in (None, exchange):
            raise HTTPException(status_code=400, detail="allocation lots must have same exchange")
        if _normalize_upper_optional(state.get("currency")) not in (None, currency):
            raise HTTPException(status_code=400, detail="allocation lots must have same currency")
        lot_fx = state.get("fx_rate_to_base") or 1.0
        if abs(lot_fx - fx_rate_to_base) > 1e-9:
            raise HTTPException(status_code=400, detail="allocation lots must have same fx_rate_to_base")

    realized_pnl_local = _compute_realized_pnl_from_allocations(
        alloc_by_lot=alloc_by_lot,
        state_at_sell=state_at_sell,
        sell_price=req.price,
        sell_fee=req.fee,
    )
    realized_pnl = _to_base(realized_pnl_local, fx_rate_to_base)

    sell_event = Event(
        type=EventType.SELL,
        ticker=ticker,
        market=market,
        exchange=exchange,
        currency=currency,
        fx_rate_to_base=fx_rate_to_base,
        trade_group_id=effective_trade_group_id,
        qty=sell_qty,
        price=req.price,
        fee=req.fee,
        reason=req.reason,
        note=req.note,
        realized_pnl=realized_pnl,
        realized_pnl_local=realized_pnl_local,
    )
    if event_ts is not None:
        sell_event.ts = event_ts
    session.add(sell_event)
    session.flush()

    for lot_id, qty_sold in alloc_by_lot.items():
        session.add(
            SellAllocation(
                sell_event_id=sell_event.id,
                lot_id=lot_id,
                qty_sold=qty_sold,
            )
        )

    session.flush()
    _assert_non_negative_lot_states(session)
    _sync_lot_snapshots_from_events(session)
    return {
        "event_id": sell_event.id,
        "realized_pnl": realized_pnl,
        "realized_pnl_local": realized_pnl_local,
        "base_currency": base_currency,
        "currency": currency,
    }


def update_lot_sl(session: Session, req: LotSLUpdateRequest) -> dict[str, Any]:
    if req.new_sl is None and req.new_tp is None:
        raise HTTPException(status_code=400, detail="new_sl or new_tp is required")
    event_ts = _normalize_optional_ts(req.ts)

    lot = session.get(Lot, req.lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail="lot not found")

    if event_ts is None:
        latest_for_lot = session.exec(
            select(Event)
            .where(Event.lot_id == lot.id)
            .order_by(Event.ts.desc(), Event.id.desc())
            .limit(1)
        ).first()
        anchor = latest_for_lot.ts if latest_for_lot is not None else lot.opened_at
        # Ensure SL_UPDATE is not written earlier than BUY/previous lot events.
        event_ts = max(datetime.utcnow(), anchor + timedelta(microseconds=1))

    if req.new_sl is not None:
        lot.sl = req.new_sl
    if req.new_tp is not None:
        lot.tp = req.new_tp

    session.add(lot)
    session.flush()

    event = Event(
        type=EventType.SL_UPDATE,
        ticker=lot.ticker,
        market=lot.market,
        exchange=lot.exchange,
        currency=lot.currency,
        fx_rate_to_base=lot.fx_rate_to_base,
        trade_group_id=lot.trade_group_id,
        lot_id=lot.id,
        sl=lot.sl,
        tp=lot.tp,
        fee=0,
        reason=req.reason,
        note=req.note,
    )
    event.ts = event_ts
    session.add(event)
    session.flush()
    _sync_lot_snapshots_from_events(session)

    return {"event_id": event.id, "lot_id": lot.id, "sl": lot.sl, "tp": lot.tp}


def create_cashflow(session: Session, req: CashflowRequest) -> dict[str, Any]:
    event_ts = _normalize_optional_ts(req.ts)
    base_currency = _get_base_currency(session)
    currency = _normalize_upper_optional(req.currency) or base_currency
    fx_rate_to_base = _resolve_fx_rate_to_base(
        base_currency,
        currency,
        req.fx_rate_to_base,
        fx_date=event_ts.date() if event_ts else None,
    )
    event = Event(
        type=EventType.CASHFLOW,
        currency=currency,
        fx_rate_to_base=fx_rate_to_base,
        fee=0,
        cash_amount=_to_base(req.cash_amount, fx_rate_to_base),
        note=req.note,
    )
    if event_ts is not None:
        event.ts = event_ts
    session.add(event)
    session.flush()
    return {"event_id": event.id}


def create_review(session: Session, req: ReviewRequest) -> dict[str, Any]:
    group = session.get(TradeGroup, req.trade_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="trade_group not found")

    group.review = req.review_text
    session.add(group)

    event = Event(
        type=EventType.REVIEW,
        trade_group_id=group.id,
        fee=0,
        review_text=req.review_text,
    )
    session.add(event)
    session.flush()

    return {"event_id": event.id, "trade_group_id": group.id}


def check_duplicate_event(session: Session, req: DuplicateCheckRequest) -> dict[str, Any]:
    event_type = _parse_event_type(req.event_type)
    market = _normalize_upper_optional(req.market)
    ticker = normalize_ticker(req.ticker, market) if req.ticker else None
    currency = _normalize_upper_optional(req.currency)
    ts = _normalize_optional_ts(req.ts)

    if ts is not None:
        start_ts = ts - timedelta(days=1)
    else:
        start_ts = datetime.utcnow() - timedelta(days=DUPLICATE_SCAN_DAYS)

    stmt = (
        select(Event)
        .where(
            Event.type == event_type,
            Event.ts >= start_ts,
        )
        .order_by(Event.ts.desc(), Event.id.desc())
    )
    if ticker:
        stmt = stmt.where(Event.ticker == ticker)

    candidates = session.exec(stmt).all()
    matches: list[dict[str, Any]] = []
    for event in candidates:
        if market and _normalize_upper_optional(event.market) != market:
            continue
        if currency and _normalize_upper_optional(event.currency) != currency:
            continue
        if ts is not None:
            delta_seconds = abs((event.ts - ts).total_seconds())
            if delta_seconds > DUPLICATE_TS_WINDOW_SECONDS:
                continue
        if req.qty is not None and not _numbers_almost_equal(event.qty, req.qty):
            continue
        if req.price is not None and not _numbers_almost_equal(event.price, req.price):
            continue
        if req.cash_amount is not None and event_type == EventType.CASHFLOW:
            if not _numbers_almost_equal(event.cash_amount, req.cash_amount):
                continue
        matches.append(
            {
                "event_id": event.id,
                "ts": event.ts.isoformat() if event.ts else None,
                "type": event.type.value,
                "ticker": event.ticker,
                "market": event.market,
                "currency": event.currency,
                "qty": event.qty,
                "price": event.price,
                "cash_amount": event.cash_amount,
            }
        )
        if len(matches) >= 5:
            break

    return {
        "event_type": event_type.value,
        "is_duplicate": len(matches) > 0,
        "duplicate_count": len(matches),
        "matches": matches,
    }


def _recompute_sell_realized_pnl(session: Session, event: Event) -> float:
    if event.type != EventType.SELL:
        return event.realized_pnl or 0.0
    if event.id is None:
        raise HTTPException(status_code=400, detail="sell event id is missing")
    if not event.ticker:
        raise HTTPException(status_code=400, detail="sell event ticker is missing")

    allocations = session.exec(select(SellAllocation).where(SellAllocation.sell_event_id == event.id)).all()
    if not allocations:
        raise HTTPException(status_code=400, detail="sell event has no allocations")

    states = _build_lot_states_before_event(session, event.id)
    alloc_by_lot: dict[int, float] = defaultdict(float)
    for alloc in allocations:
        alloc_by_lot[alloc.lot_id] += alloc.qty_sold

    realized_local = _compute_realized_pnl_from_allocations(
        alloc_by_lot=alloc_by_lot,
        state_at_sell=states,
        sell_price=event.price or 0.0,
        sell_fee=event.fee or 0.0,
    )
    event.realized_pnl_local = realized_local
    return _to_base(realized_local, event.fx_rate_to_base)


def update_event(session: Session, event_id: int, req: EventUpdateRequest) -> dict[str, Any]:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    changed = req.model_dump(exclude_unset=True)
    if not changed:
        return {"event_id": event_id, "updated": False}

    if "ticker" in changed:
        if req.ticker is None:
            raise HTTPException(status_code=400, detail="ticker cannot be null")
        ticker_market = req.market if "market" in changed else event.market
        event.ticker = normalize_ticker(req.ticker, ticker_market)

    if "ts" in changed:
        event.ts = _normalize_optional_ts(req.ts) or event.ts
    if "market" in changed:
        event.market = _normalize_upper_optional(req.market)
    if "exchange" in changed:
        event.exchange = _normalize_upper_optional(req.exchange)
    if "currency" in changed:
        event.currency = _normalize_upper_optional(req.currency)
    if "fx_rate_to_base" in changed:
        if req.fx_rate_to_base is None:
            raise HTTPException(status_code=400, detail="fx_rate_to_base cannot be null")
        event.fx_rate_to_base = req.fx_rate_to_base
    if "trade_group_id" in changed:
        if req.trade_group_id is not None:
            group = session.get(TradeGroup, req.trade_group_id)
            if group is None:
                raise HTTPException(status_code=400, detail="trade_group_id does not exist")
        event.trade_group_id = req.trade_group_id
    if "reason" in changed:
        event.reason = _normalize_optional_text(req.reason)
    if "note" in changed:
        event.note = _normalize_optional_text(req.note)
    if "image_url" in changed:
        event.image_url = _normalize_optional_text(req.image_url)

    lot: Lot | None = None
    if event.type == EventType.BUY:
        if event.lot_id is None:
            raise HTTPException(status_code=400, detail="buy event has no lot")
        lot = session.get(Lot, event.lot_id)
        if lot is None:
            raise HTTPException(status_code=400, detail="linked lot not found")

        if "ticker" in changed:
            lot.ticker = event.ticker
        if "qty" in changed:
            if req.qty is None:
                raise HTTPException(status_code=400, detail="BUY qty cannot be null")
            event.qty = req.qty
        if "price" in changed:
            if req.price is None:
                raise HTTPException(status_code=400, detail="BUY price cannot be null")
            event.price = req.price
        if "fee" in changed:
            if req.fee is None:
                raise HTTPException(status_code=400, detail="BUY fee cannot be null")
            event.fee = req.fee
        if "sl" in changed:
            event.sl = req.sl
        if "tp" in changed:
            event.tp = req.tp

        lot.entry_price = event.price or 0.0
        lot.buy_fee = event.fee or 0.0
        lot.market = event.market
        lot.exchange = event.exchange
        lot.currency = event.currency
        lot.fx_rate_to_base = event.fx_rate_to_base or 1.0
        lot.trade_group_id = event.trade_group_id
        lot.sl = event.sl
        lot.tp = event.tp
        lot.buy_reason = event.reason
        lot.note = event.note
        lot.opened_at = event.ts
        session.add(lot)
        if event.ticker:
            _ensure_symbol(
                session,
                event.ticker,
                market=event.market,
                exchange=event.exchange,
                currency=event.currency,
            )

    elif event.type == EventType.SELL:
        if "ticker" in changed:
            if event.id is None:
                raise HTTPException(status_code=400, detail="sell event id is missing")
            allocations = session.exec(select(SellAllocation).where(SellAllocation.sell_event_id == event.id)).all()
            if allocations:
                lot_ids = [alloc.lot_id for alloc in allocations]
                lots = session.exec(select(Lot).where(Lot.id.in_(lot_ids))).all()
                for lot in lots:
                    if lot.ticker != event.ticker:
                        raise HTTPException(
                            status_code=400,
                            detail="SELL ticker must match allocated lot ticker",
                        )
        if "price" in changed:
            if req.price is None:
                raise HTTPException(status_code=400, detail="SELL price cannot be null")
            event.price = req.price
        if "fee" in changed:
            if req.fee is None:
                raise HTTPException(status_code=400, detail="SELL fee cannot be null")
            event.fee = req.fee
        if "qty" in changed:
            raise HTTPException(status_code=400, detail="SELL qty edit is not supported; edit allocations instead")
        event.realized_pnl = _recompute_sell_realized_pnl(session, event)

    elif event.type == EventType.CASHFLOW:
        if "ticker" in changed:
            raise HTTPException(status_code=400, detail="CASHFLOW ticker edit is not supported")
        if "cash_amount" in changed:
            if req.cash_amount is None:
                raise HTTPException(status_code=400, detail="cash_amount cannot be null")
            event.cash_amount = req.cash_amount

    elif event.type == EventType.SL_UPDATE:
        if "ticker" in changed:
            raise HTTPException(status_code=400, detail="SL_UPDATE ticker edit is not supported")
        if "sl" in changed:
            event.sl = req.sl
        if "tp" in changed:
            event.tp = req.tp
        if event.lot_id is not None:
            lot = session.get(Lot, event.lot_id)
            if lot is not None:
                lot.trade_group_id = event.trade_group_id
                lot.sl = event.sl
                lot.tp = event.tp
                session.add(lot)

    elif event.type == EventType.REVIEW:
        if "ticker" in changed:
            raise HTTPException(status_code=400, detail="REVIEW ticker edit is not supported")
        if "review_text" in changed:
            event.review_text = _normalize_optional_text(req.review_text)

    session.add(event)
    session.flush()
    _assert_non_negative_lot_states(session)
    _sync_lot_snapshots_from_events(session)

    return {"event_id": event_id, "updated": True}


def delete_event(session: Session, event_id: int) -> dict[str, Any]:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    if event.type == EventType.BUY:
        if event.lot_id is None:
            raise HTTPException(status_code=400, detail="buy event has no lot")

        sell_alloc_exists = session.exec(
            select(SellAllocation).where(SellAllocation.lot_id == event.lot_id)
        ).first()
        if sell_alloc_exists is not None:
            raise HTTPException(
                status_code=400,
                detail="cannot delete BUY with related SELL allocations; delete those SELL events first",
            )

        sl_update_exists = session.exec(
            select(Event).where(
                Event.type == EventType.SL_UPDATE,
                Event.lot_id == event.lot_id,
                Event.id != event.id,
            )
        ).first()
        if sl_update_exists is not None:
            raise HTTPException(
                status_code=400,
                detail="cannot delete BUY with related SL_UPDATE events; delete those SL_UPDATE events first",
            )

        lot = session.get(Lot, event.lot_id)
        if lot is not None:
            session.delete(lot)
        session.delete(event)

    elif event.type == EventType.SELL:
        allocs = session.exec(select(SellAllocation).where(SellAllocation.sell_event_id == event.id)).all()
        for alloc in allocs:
            session.delete(alloc)
        session.delete(event)

    else:
        session.delete(event)

    session.flush()
    _assert_non_negative_lot_states(session)
    _sync_lot_snapshots_from_events(session)
    return {"event_id": event_id, "deleted": True}


def calc_lot_open_risk(lot: Lot, est_exit_fee_rate: float = 0.0) -> float:
    return _calc_open_risk_from_values(
        entry_price=lot.entry_price,
        sl=lot.sl,
        qty_open=lot.qty_open,
        fx_rate_to_base=lot.fx_rate_to_base,
        est_exit_fee_rate=est_exit_fee_rate,
    )


def calc_lot_open_risk_local(lot: Lot, est_exit_fee_rate: float = 0.0) -> float:
    return _calc_open_risk_from_values(
        entry_price=lot.entry_price,
        sl=lot.sl,
        qty_open=lot.qty_open,
        fx_rate_to_base=1.0,
        est_exit_fee_rate=est_exit_fee_rate,
    )


def _calc_open_risk_from_values(
    entry_price: float,
    sl: float | None,
    qty_open: float,
    fx_rate_to_base: float = 1.0,
    est_exit_fee_rate: float = 0.0,
) -> float:
    if sl is None or qty_open <= 0:
        return 0.0

    base = max(0.0, (entry_price - sl) * qty_open)
    if est_exit_fee_rate > 0:
        base += est_exit_fee_rate * (sl * qty_open)
    return _to_base(base, fx_rate_to_base)


def event_amount(event: Event) -> float | None:
    qty = event.qty or 0
    price = event.price or 0
    fx_rate_to_base = event.fx_rate_to_base or 1.0
    if event.type == EventType.BUY:
        return _to_base(-(qty * price + event.fee), fx_rate_to_base)
    if event.type == EventType.SELL:
        return _to_base(qty * price - event.fee, fx_rate_to_base)
    if event.type == EventType.CASHFLOW:
        return event.cash_amount or 0
    return None


def get_cash_balance(session: Session) -> float:
    events = session.exec(select(Event)).all()
    cash = 0.0
    for event in events:
        amount = event_amount(event)
        if amount is not None:
            cash += amount
    return cash


def get_cashflow_balance(session: Session) -> float:
    events = session.exec(select(Event)).all()
    return sum((event.cash_amount or 0.0) for event in events if event.type == EventType.CASHFLOW)


def _has_cashflow_events(session: Session) -> bool:
    first_cashflow = session.exec(
        select(Event.id).where(Event.type == EventType.CASHFLOW).limit(1)
    ).first()
    return first_cashflow is not None


def get_open_position_cost(session: Session) -> float:
    lots = session.exec(select(Lot).where(Lot.qty_open > 0)).all()
    return sum(_to_base(lot.entry_price * lot.qty_open, lot.fx_rate_to_base) for lot in lots)


def get_open_position_mtm(session: Session) -> float:
    return _current_open_market_value(session)


def get_book_asset_cost(session: Session) -> float:
    open_cost = get_open_position_cost(session)
    if not _has_cashflow_events(session):
        return open_cost
    return get_cash_balance(session) + open_cost


def get_book_asset_mtm(session: Session) -> float:
    open_market_value = get_open_position_mtm(session)
    if not _has_cashflow_events(session):
        # If deposits are not tracked yet, show ledger asset as current position value.
        return open_market_value
    return get_cash_balance(session) + open_market_value


def get_book_asset(session: Session) -> float:
    # Backward-compatible alias: Book Asset defaults to MTM view.
    return get_book_asset_mtm(session)


def _symbol_name_map(session: Session) -> dict[str, str]:
    symbols = session.exec(select(Symbol)).all()
    return {s.ticker: (s.name or s.ticker) for s in symbols}


def build_portfolio(session: Session) -> dict[str, Any]:
    settings = session.get(Setting, 1)
    est_exit_fee_rate = settings.est_exit_fee_rate if settings else 0.0
    base_currency = _get_base_currency(session)

    lots = session.exec(select(Lot).where(Lot.qty_open > 0)).all()
    lot_ids = [lot.id for lot in lots if lot.id is not None]
    buy_event_by_lot_id: dict[int, Event] = {}
    if lot_ids:
        buy_events = session.exec(
            select(Event)
            .where(
                Event.type == EventType.BUY,
                Event.lot_id.in_(lot_ids),
            )
            .order_by(Event.ts.asc(), Event.id.asc())
        ).all()
        for buy_event in buy_events:
            if buy_event.lot_id is None:
                continue
            buy_event_by_lot_id.setdefault(buy_event.lot_id, buy_event)
    symbol_names = _symbol_name_map(session)

    by_ticker: dict[tuple[str, str | None, str | None, str | None], list[Lot]] = defaultdict(list)
    for lot in lots:
        key = (
            lot.ticker,
            _normalize_upper_optional(lot.market),
            _normalize_upper_optional(lot.exchange),
            _normalize_upper_optional(lot.currency),
        )
        by_ticker[key].append(lot)

    sells_by_key: dict[tuple[str, str | None, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    sell_events = session.exec(
        select(Event)
        .where(Event.type == EventType.SELL)
        .order_by(Event.ts.desc(), Event.id.desc())
    ).all()
    sell_event_ids = [event.id for event in sell_events if event.id is not None]
    allocs_by_event: dict[int, list[SellAllocation]] = defaultdict(list)
    lots_by_id: dict[int, Lot] = {}
    if sell_event_ids:
        sell_allocs = session.exec(
            select(SellAllocation)
            .where(SellAllocation.sell_event_id.in_(sell_event_ids))
            .order_by(SellAllocation.sell_event_id.asc(), SellAllocation.id.asc())
        ).all()
        lot_ids_for_allocs: set[int] = set()
        for alloc in sell_allocs:
            allocs_by_event[alloc.sell_event_id].append(alloc)
            lot_ids_for_allocs.add(alloc.lot_id)

        if lot_ids_for_allocs:
            lots_for_allocs = session.exec(select(Lot).where(Lot.id.in_(sorted(lot_ids_for_allocs)))).all()
            lots_by_id = {lot.id: lot for lot in lots_for_allocs if lot.id is not None}

    for sell_event in sell_events:
        if sell_event.id is None:
            continue
        alloc_list = allocs_by_event.get(sell_event.id, [])
        allocation_rows: list[dict[str, Any]] = []
        for alloc in alloc_list:
            lot = lots_by_id.get(alloc.lot_id)
            allocation_rows.append(
                {
                    "lot_id": alloc.lot_id,
                    "qty_sold": alloc.qty_sold,
                    "ticker": lot.ticker if lot is not None else None,
                    "market": _normalize_upper_optional(lot.market if lot is not None else None),
                    "exchange": _normalize_upper_optional(lot.exchange if lot is not None else None),
                    "currency": _normalize_upper_optional(lot.currency if lot is not None else None),
                    "trade_group_id": lot.trade_group_id if lot is not None else None,
                }
            )
        allocation_rows.sort(key=lambda row: row.get("lot_id") or 0)

        ticker = (sell_event.ticker or "").strip().upper()
        market = _normalize_upper_optional(sell_event.market)
        exchange = _normalize_upper_optional(sell_event.exchange)
        currency = _normalize_upper_optional(sell_event.currency)
        if allocation_rows:
            first_alloc = allocation_rows[0]
            if not ticker:
                ticker = (first_alloc.get("ticker") or "").strip().upper()
            if market is None:
                market = first_alloc.get("market")
            if exchange is None:
                exchange = first_alloc.get("exchange")
            if currency is None:
                currency = first_alloc.get("currency")
        if not ticker:
            continue

        allocation_labels = [
            f"lot#{int(item['lot_id'])} ({item['qty_sold']:,.4f})"
            for item in allocation_rows
            if item.get("lot_id") is not None
        ]
        sells_by_key[(ticker, market, exchange, currency)].append(
            {
                "event_id": sell_event.id,
                "ts": sell_event.ts,
                "ticker": ticker,
                "market": market,
                "exchange": exchange,
                "currency": currency,
                "currency_symbol": _currency_symbol(currency),
                "qty": sell_event.qty,
                "price": sell_event.price,
                "price_display": _format_price_for_display(sell_event.price),
                "fee": sell_event.fee or 0.0,
                "fee_local": sell_event.fee or 0.0,
                "realized_pnl": sell_event.realized_pnl or 0.0,
                "realized_pnl_local": (
                    sell_event.realized_pnl_local
                    if sell_event.realized_pnl_local is not None
                    else (
                        (sell_event.realized_pnl or 0.0)
                        / (sell_event.fx_rate_to_base or 1.0)
                    )
                ),
                "reason": sell_event.reason,
                "note": sell_event.note,
                "sell_lot_label": f"sell#{sell_event.id}",
                "allocation_text": ", ".join(allocation_labels) if allocation_labels else "-",
                "allocations": allocation_rows,
            }
        )

    cash_balance = get_cashflow_balance(session)
    open_position_mtm = get_open_position_mtm(session)
    open_position_cost = get_open_position_cost(session)
    book_asset_mtm = get_book_asset_mtm(session)
    book_asset_cost = get_book_asset_cost(session)
    book_asset = book_asset_mtm
    # Open risk percentage is more stable when anchored to invested capital.
    risk_pct_denominator = open_position_cost if open_position_cost > 0 else book_asset

    rows: list[dict[str, Any]] = []
    total_cost_amount = sum(_to_base(lot.entry_price * lot.qty_open, lot.fx_rate_to_base) for lot in lots)

    for key in sorted(by_ticker.keys(), key=lambda k: (k[0], k[1] or "", k[2] or "", k[3] or "")):
        ticker, market, exchange, currency = key
        ticker_lots = sorted(by_ticker[key], key=lambda x: (x.opened_at, x.id or 0))
        qty_open = sum(lot.qty_open for lot in ticker_lots)
        amount_cost = sum(_to_base(lot.entry_price * lot.qty_open, lot.fx_rate_to_base) for lot in ticker_lots)
        amount_cost_local = sum(lot.entry_price * lot.qty_open for lot in ticker_lots)
        avg_entry_price = amount_cost / qty_open if qty_open else 0.0
        avg_entry_price_local = amount_cost_local / qty_open if qty_open else 0.0

        open_risk = sum(calc_lot_open_risk(lot, est_exit_fee_rate) for lot in ticker_lots)
        open_risk_local = sum(calc_lot_open_risk_local(lot, est_exit_fee_rate) for lot in ticker_lots)
        open_risk_pct = (open_risk / amount_cost * 100) if amount_cost else 0.0
        open_risk_pct_local = (open_risk_local / amount_cost_local * 100) if amount_cost_local else 0.0
        open_risk_total_cost_pct = (open_risk / total_cost_amount * 100) if total_cost_amount else 0.0

        sl_tp_pairs = {(lot.sl, lot.tp) for lot in ticker_lots}
        if len(sl_tp_pairs) == 1:
            sl, tp = next(iter(sl_tp_pairs))
            sl_str = "None" if sl is None else _format_sl_tp_value(sl)
            tp_str = "None" if tp is None else _format_sl_tp_value(tp)
            sl_tp = f"SL {sl_str} / TP {tp_str}"
        else:
            sl_tp = "mixed"

        lots_out = [
            {
                "lot_id": lot.id,
                "opened_at": lot.opened_at,
                "qty_open": lot.qty_open,
                "market": lot.market,
                "exchange": lot.exchange,
                "currency": lot.currency,
                "currency_symbol": _currency_symbol(lot.currency),
                "fx_rate_to_base": lot.fx_rate_to_base,
                "entry_price": lot.entry_price,
                "sl": lot.sl,
                "tp": lot.tp,
                "sl_display": _format_sl_tp_value(lot.sl),
                "tp_display": _format_sl_tp_value(lot.tp),
                "buy_fee": lot.buy_fee,
                "buy_fee_local": lot.buy_fee,
                "buy_reason": lot.buy_reason,
                "note": lot.note,
                "open_risk": calc_lot_open_risk(lot, est_exit_fee_rate),
                "open_risk_local": calc_lot_open_risk_local(lot, est_exit_fee_rate),
                "buy_event_id": (
                    buy_event_by_lot_id.get(lot.id).id
                    if lot.id is not None and buy_event_by_lot_id.get(lot.id) is not None
                    else None
                ),
            }
            for lot in ticker_lots
        ]

        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "exchange": exchange,
                "currency": currency,
                "currency_symbol": _currency_symbol(currency),
                "symbol_name": symbol_names.get(ticker, ticker),
                "qty_open": qty_open,
                "avg_entry_price": avg_entry_price,
                "avg_entry_price_local": avg_entry_price_local,
                "sl_tp": sl_tp,
                "amount_cost": amount_cost,
                "amount_cost_local": amount_cost_local,
                "open_risk": open_risk,
                "open_risk_local": open_risk_local,
                "open_risk_pct": open_risk_pct,
                "open_risk_pct_local": open_risk_pct_local,
                "open_risk_total_cost_pct": open_risk_total_cost_pct,
                "lots": lots_out,
                "sell_events": sells_by_key.get(key, []),
            }
        )

    totals = {
        "qty_open": sum(row["qty_open"] for row in rows),
        "amount_cost": sum(row["amount_cost"] for row in rows),
        "open_risk": sum(row["open_risk"] for row in rows),
    }
    totals["open_risk_pct"] = (
        (totals["open_risk"] / risk_pct_denominator * 100) if risk_pct_denominator else 0.0
    )
    totals["open_risk_total_cost_pct"] = (
        (totals["open_risk"] / totals["amount_cost"] * 100) if totals["amount_cost"] else 0.0
    )

    return {
        "base_currency": base_currency,
        "base_currency_symbol": _currency_symbol(base_currency),
        "krw_currency_symbol": _currency_symbol("KRW"),
        "usd_currency_symbol": _currency_symbol("USD"),
        "cash_balance": cash_balance,
        "cash_balance_dual": _dual_currency_from_base(cash_balance, base_currency),
        "open_position_mtm": open_position_mtm,
        "open_position_mtm_dual": _dual_currency_from_base(open_position_mtm, base_currency),
        "open_position_cost": open_position_cost,
        "open_position_cost_dual": _dual_currency_from_base(open_position_cost, base_currency),
        "book_asset": book_asset,
        "book_asset_mtm": book_asset_mtm,
        "book_asset_cost": book_asset_cost,
        "risk_pct_denominator": risk_pct_denominator,
        "totals_amount_cost_dual": _dual_currency_from_base(totals["amount_cost"], base_currency),
        "totals_open_risk_dual": _dual_currency_from_base(totals["open_risk"], base_currency),
        "rows": rows,
        "totals": totals,
    }


def _fetch_daily_highs_from_yahoo_chart_symbol(
    symbol: str,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    if start_date > end_date:
        return {}
    period1 = int(datetime.combine(start_date, time.min).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), time.min).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}?interval=1d&period1={period1}&period2={period2}"
        "&events=history&includeAdjustedClose=true"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}

    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results:
        return {}

    result = results[0] if isinstance(results[0], dict) else {}
    timestamps = result.get("timestamp") if isinstance(result, dict) else None
    indicators = result.get("indicators") if isinstance(result, dict) else None
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote0 = quotes[0] if isinstance(quotes, list) and quotes else {}
    highs = quote0.get("high") if isinstance(quote0, dict) else None

    if not isinstance(timestamps, list) or not isinstance(highs, list):
        return {}

    output: dict[date, float] = {}
    for ts_value, high_value in zip(timestamps, highs):
        try:
            ts_int = int(ts_value)
        except (TypeError, ValueError):
            continue
        day = datetime.utcfromtimestamp(ts_int).date()
        if day < start_date or day > end_date:
            continue
        parsed_high = _parse_positive_float(high_value)
        if parsed_high is None:
            continue
        previous = output.get(day)
        output[day] = parsed_high if previous is None else max(previous, parsed_high)
    return output


def _fetch_daily_highs_from_naver_kr(
    ticker: str,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    digits = "".join(ch for ch in (ticker or "") if ch.isdigit()).zfill(6)
    if len(digits) != 6 or start_date > end_date:
        return {}

    history_days = max(30, (datetime.utcnow().date() - start_date).days + 40)
    count = min(6000, history_days)
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={digits}&timeframe=day&count={count}&requestType=0"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read()
    except Exception:
        return {}

    decoded = None
    for encoding in ("euc-kr", "cp949", "utf-8"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        return {}

    try:
        root = ET.fromstring(decoded)
    except ET.ParseError:
        return {}

    output: dict[date, float] = {}
    for item in root.findall(".//item"):
        packed = item.attrib.get("data", "")
        if not packed:
            continue
        parts = packed.split("|")
        if len(parts) < 3:
            continue
        try:
            day = datetime.strptime(parts[0], "%Y%m%d").date()
        except ValueError:
            continue
        if day < start_date or day > end_date:
            continue
        parsed_high = _parse_positive_float(parts[2])
        if parsed_high is None:
            continue
        previous = output.get(day)
        output[day] = parsed_high if previous is None else max(previous, parsed_high)
    return output


def _get_daily_highs_for_range(
    ticker: str | None,
    market: str | None,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    if start_date > end_date:
        return {}
    normalized_ticker = (ticker or "").strip().upper()
    if not normalized_ticker:
        return {}
    normalized_market = _normalize_upper_optional(market)
    now_ts = datetime.utcnow().timestamp()

    if _should_use_naver_kr_source(normalized_ticker, normalized_market):
        naver_key = (
            f"NAVER_HIGH:{''.join(ch for ch in normalized_ticker if ch.isdigit()).zfill(6)}:"
            f"{start_date.isoformat()}:{end_date.isoformat()}"
        )
        cached = _daily_high_cache.get(naver_key)
        if cached and now_ts - float(cached.get("fetched_at", 0.0) or 0.0) < DAILY_HIGH_CACHE_TTL_SECONDS:
            return dict(cached.get("highs") or {})

        naver_highs = _fetch_daily_highs_from_naver_kr(normalized_ticker, start_date, end_date)
        _daily_high_cache[naver_key] = {"fetched_at": now_ts, "highs": naver_highs}
        if naver_highs:
            return naver_highs

    for symbol in _quote_symbol_candidates(normalized_ticker, normalized_market):
        cache_key = f"YAHOO_HIGH:{symbol}:{start_date.isoformat()}:{end_date.isoformat()}"
        cached = _daily_high_cache.get(cache_key)
        if cached and now_ts - float(cached.get("fetched_at", 0.0) or 0.0) < DAILY_HIGH_CACHE_TTL_SECONDS:
            highs = dict(cached.get("highs") or {})
            if highs:
                return highs
            continue

        highs = _fetch_daily_highs_from_yahoo_chart_symbol(symbol, start_date, end_date)
        _daily_high_cache[cache_key] = {"fetched_at": now_ts, "highs": highs}
        if highs:
            return highs

    return {}


def _max_high_in_range(highs_by_date: dict[date, float], start_date: date, end_date: date) -> float | None:
    if start_date > end_date:
        return None
    best: float | None = None
    for day, high in highs_by_date.items():
        if day < start_date or day > end_date:
            continue
        if best is None or high > best:
            best = high
    return best


def _attach_sell_vs_peak_metrics(
    session: Session,
    rows: list[dict[str, Any]],
    sell_alloc_map: dict[int, list[SellAllocation]],
) -> None:
    if not rows:
        return

    sell_row_by_id: dict[int, dict[str, Any]] = {}
    lot_ids: set[int] = set()

    for row in rows:
        row.setdefault("sell_vs_peak_status", "")
        row.setdefault("sell_vs_peak_pct", None)
        row.setdefault("sell_vs_peak_amount", None)
        if str(row.get("type") or "").upper() != EventType.SELL.value:
            continue
        event_id = row.get("id")
        if event_id is None:
            continue
        try:
            sell_id = int(event_id)
        except (TypeError, ValueError):
            continue
        sell_row_by_id[sell_id] = row
        for alloc in sell_alloc_map.get(sell_id, []):
            lot_ids.add(alloc.lot_id)

    if not sell_row_by_id or not lot_ids:
        return

    lots = session.exec(select(Lot).where(Lot.id.in_(sorted(lot_ids)))).all()
    lot_map = {lot.id: lot for lot in lots if lot.id is not None}

    range_bounds: dict[tuple[str, str | None], dict[str, date]] = {}
    sell_segments: dict[int, list[dict[str, Any]]] = defaultdict(list)
    sell_flags: dict[int, dict[str, bool]] = {}

    for sell_id, row in sell_row_by_id.items():
        row["sell_vs_peak_status"] = "na"
        row["sell_vs_peak_pct"] = None
        row["sell_vs_peak_amount"] = None

        ts_value = row.get("ts")
        sell_date: date | None = None
        if isinstance(ts_value, datetime):
            sell_date = ts_value.date()
        elif isinstance(ts_value, date):
            sell_date = ts_value
        elif isinstance(ts_value, str):
            text = ts_value.strip()
            if text:
                try:
                    sell_date = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
                except ValueError:
                    try:
                        sell_date = date.fromisoformat(text[:10])
                    except ValueError:
                        sell_date = None
        if sell_date is None:
            continue

        try:
            sell_price = float(row.get("price"))
        except (TypeError, ValueError):
            sell_price = 0.0
        if not math.isfinite(sell_price) or sell_price <= 0:
            continue

        flags = {"has_alloc": False, "has_daytrade": False}
        for alloc in sell_alloc_map.get(sell_id, []):
            flags["has_alloc"] = True
            lot = lot_map.get(alloc.lot_id)
            if lot is None:
                continue
            buy_date = lot.opened_at.date()
            if buy_date >= sell_date:
                flags["has_daytrade"] = True
                continue

            start_date = buy_date + timedelta(days=1)
            end_date = sell_date
            if start_date > end_date:
                flags["has_daytrade"] = True
                continue

            qty_sold = float(alloc.qty_sold or 0.0)
            if qty_sold <= 0:
                continue

            ticker = (lot.ticker or row.get("ticker") or "").strip().upper()
            market = _normalize_upper_optional(lot.market if lot.market is not None else row.get("market"))
            fx_rate = lot.fx_rate_to_base or row.get("fx_rate_to_base") or 1.0
            if not math.isfinite(float(fx_rate)) or float(fx_rate) <= 0:
                fx_rate = 1.0

            key = (ticker, market)
            sell_segments[sell_id].append(
                {
                    "key": key,
                    "start_date": start_date,
                    "end_date": end_date,
                    "qty_sold": qty_sold,
                    "sell_price": sell_price,
                    "fx_rate_to_base": float(fx_rate),
                }
            )

            bounds = range_bounds.setdefault(key, {"start_date": start_date, "end_date": end_date})
            if start_date < bounds["start_date"]:
                bounds["start_date"] = start_date
            if end_date > bounds["end_date"]:
                bounds["end_date"] = end_date

        sell_flags[sell_id] = flags

    highs_by_key: dict[tuple[str, str | None], dict[date, float]] = {}
    for key, bounds in range_bounds.items():
        ticker, market = key
        highs_by_key[key] = _get_daily_highs_for_range(
            ticker=ticker,
            market=market,
            start_date=bounds["start_date"],
            end_date=bounds["end_date"],
        )

    for sell_id, row in sell_row_by_id.items():
        segments = sell_segments.get(sell_id, [])
        weighted_pct_sum = 0.0
        weighted_qty_sum = 0.0
        missed_amount_base = 0.0

        for segment in segments:
            highs = highs_by_key.get(segment["key"], {})
            max_high = _max_high_in_range(
                highs,
                segment["start_date"],
                segment["end_date"],
            )
            if max_high is None or max_high <= 0:
                continue

            sell_price = segment["sell_price"]
            diff = max(0.0, max_high - sell_price)
            qty_sold = segment["qty_sold"]
            pct = (diff / max_high) * 100.0
            weighted_pct_sum += pct * qty_sold
            weighted_qty_sum += qty_sold
            missed_amount_base += diff * qty_sold * segment["fx_rate_to_base"]

        if weighted_qty_sum > 0:
            row["sell_vs_peak_status"] = "ok"
            row["sell_vs_peak_pct"] = weighted_pct_sum / weighted_qty_sum
            row["sell_vs_peak_amount"] = missed_amount_base
            continue

        flags = sell_flags.get(sell_id, {})
        if flags.get("has_daytrade") and flags.get("has_alloc"):
            row["sell_vs_peak_status"] = "daytrade"
        else:
            row["sell_vs_peak_status"] = "na"


def build_journal(
    session: Session,
    page: int = 1,
    page_size: int = 200,
    query: str | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    hf_ticker: list[str] | None = None,
    hf_market: list[str] | None = None,
    hf_currency: list[str] | None = None,
    hf_symbol_name: list[str] | None = None,
    hf_type: list[str] | None = None,
    hf_win_lose: list[str] | None = None,
) -> dict[str, Any]:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1

    events = session.exec(select(Event).order_by(Event.ts.asc(), Event.id.asc())).all()
    symbol_names = _symbol_name_map(session)
    trade_groups = session.exec(select(TradeGroup)).all()
    trade_group_map = {g.id: g for g in trade_groups}
    settings = session.get(Setting, 1)
    est_exit_fee_rate = settings.est_exit_fee_rate if settings else 0.0
    base_currency = _get_base_currency(session)
    unrealized_by_lot_id, unrealized_by_key = _build_open_unrealized_pnl_maps(session)

    has_cashflow_events = _has_cashflow_events(session)
    current_book_asset = get_book_asset(session)
    current_book_asset_mtm = get_book_asset_mtm(session)
    current_book_asset_cost = get_book_asset_cost(session)
    cash_balance_trade = get_cash_balance(session)
    cash_balance = get_cashflow_balance(session)
    open_position_mtm = get_open_position_mtm(session)
    open_position_cost = get_open_position_cost(session)
    sell_event_ids = [event.id for event in events if event.type == EventType.SELL and event.id is not None]
    sell_alloc_map: dict[int, list[SellAllocation]] = defaultdict(list)
    if sell_event_ids:
        allocs = session.exec(
            select(SellAllocation)
            .where(SellAllocation.sell_event_id.in_(sell_event_ids))
            .order_by(SellAllocation.id.asc())
        ).all()
        for alloc in allocs:
            sell_alloc_map[alloc.sell_event_id].append(alloc)

    lot_states: dict[int, dict[str, Any]] = {}
    open_risk_snapshots: dict[int, dict[str, Any]] = {}
    book_asset_snapshots: dict[int, float] = {}
    running_open_risk = 0.0
    running_cash_balance = 0.0

    for event in events:
        risk_delta = 0.0
        risk_delta_details: list[str] = []

        if event.type == EventType.BUY and event.lot_id is not None:
            qty = event.qty or 0.0
            entry_price = event.price or 0.0
            fee = event.fee or 0.0
            running_cash_balance -= _to_base((qty * entry_price + fee), event.fx_rate_to_base)
            lot_states[event.lot_id] = {
                "entry_price": entry_price,
                "qty_open": qty,
                "sl": event.sl,
                "tp": event.tp,
                "market": event.market,
                "exchange": event.exchange,
                "currency": event.currency,
                "fx_rate_to_base": event.fx_rate_to_base or 1.0,
            }
            risk_delta = _calc_open_risk_from_values(
                entry_price=entry_price,
                sl=event.sl,
                qty_open=qty,
                fx_rate_to_base=event.fx_rate_to_base or 1.0,
                est_exit_fee_rate=est_exit_fee_rate,
            )
            risk_delta_details.append(f"lot#{event.lot_id} {risk_delta:+.2f}")

        elif event.type == EventType.SELL and event.id is not None:
            qty = event.qty or 0.0
            price = event.price or 0.0
            fee = event.fee or 0.0
            running_cash_balance += _to_base((qty * price - fee), event.fx_rate_to_base)
            for alloc in sell_alloc_map.get(event.id, []):
                lot_state = lot_states.get(alloc.lot_id)
                if lot_state is None:
                    continue

                before = _calc_open_risk_from_values(
                    entry_price=lot_state["entry_price"],
                    sl=lot_state["sl"],
                    qty_open=lot_state["qty_open"],
                    fx_rate_to_base=lot_state.get("fx_rate_to_base", 1.0),
                    est_exit_fee_rate=est_exit_fee_rate,
                )
                lot_state["qty_open"] = max(0.0, lot_state["qty_open"] - alloc.qty_sold)
                after = _calc_open_risk_from_values(
                    entry_price=lot_state["entry_price"],
                    sl=lot_state["sl"],
                    qty_open=lot_state["qty_open"],
                    fx_rate_to_base=lot_state.get("fx_rate_to_base", 1.0),
                    est_exit_fee_rate=est_exit_fee_rate,
                )
                lot_delta = after - before
                risk_delta += lot_delta
                risk_delta_details.append(f"lot#{alloc.lot_id} {lot_delta:+.2f}")

        elif event.type == EventType.SL_UPDATE and event.lot_id is not None:
            lot_state = lot_states.get(event.lot_id)
            if lot_state is not None:
                before = _calc_open_risk_from_values(
                    entry_price=lot_state["entry_price"],
                    sl=lot_state["sl"],
                    qty_open=lot_state["qty_open"],
                    fx_rate_to_base=lot_state.get("fx_rate_to_base", 1.0),
                    est_exit_fee_rate=est_exit_fee_rate,
                )
                lot_state["sl"] = event.sl
                lot_state["tp"] = event.tp
                after = _calc_open_risk_from_values(
                    entry_price=lot_state["entry_price"],
                    sl=lot_state["sl"],
                    qty_open=lot_state["qty_open"],
                    fx_rate_to_base=lot_state.get("fx_rate_to_base", 1.0),
                    est_exit_fee_rate=est_exit_fee_rate,
                )
                risk_delta = after - before
                risk_delta_details.append(f"lot#{event.lot_id} {risk_delta:+.2f}")
        elif event.type == EventType.CASHFLOW:
            running_cash_balance += event.cash_amount or 0.0

        running_open_risk += risk_delta
        if abs(running_open_risk) < 1e-12:
            running_open_risk = 0.0

        if event.id is not None:
            snapshot_open_cost = _current_open_cost(lot_states)
            if has_cashflow_events:
                book_asset_snapshots[event.id] = running_cash_balance + snapshot_open_cost
            else:
                book_asset_snapshots[event.id] = snapshot_open_cost
            open_risk_snapshots[event.id] = {
                "open_risk": running_open_risk,
                "open_risk_delta": risk_delta,
                "open_risk_delta_details": ", ".join(risk_delta_details) if risk_delta_details else None,
            }

    normalized_query = (query or "").strip().lower()
    normalized_event_type = (event_type or "").strip().upper()
    if normalized_event_type and normalized_event_type not in {e.value for e in EventType}:
        raise HTTPException(status_code=400, detail="invalid event_type")

    ts_from: datetime | None = datetime.combine(date_from, time.min) if date_from else None
    ts_to: datetime | None = datetime.combine(date_to, time.max) if date_to else None
    if ts_from and ts_to and ts_from > ts_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    filtered_events: list[Event] = []
    for event in events:
        if normalized_event_type and event.type.value != normalized_event_type:
            continue
        if ts_from and event.ts < ts_from:
            continue
        if ts_to and event.ts > ts_to:
            continue
        if normalized_query:
            group = trade_group_map.get(event.trade_group_id) if event.trade_group_id else None
            review_text = event.review_text if event.type == EventType.REVIEW else (group.review if group else None)
            haystack = " ".join(
                [
                    event.type.value,
                    event.ticker or "",
                    symbol_names.get(event.ticker, event.ticker) if event.ticker else "",
                    event.reason or "",
                    event.note or "",
                    review_text or "",
                ]
            ).lower()
            if normalized_query not in haystack:
                continue
        filtered_events.append(event)

    rows_all = []
    for event in reversed(filtered_events):
        group = trade_group_map.get(event.trade_group_id) if event.trade_group_id else None
        review_text = event.review_text if event.type == EventType.REVIEW else (group.review if group else None)
        symbol_name = symbol_names.get(event.ticker, event.ticker) if event.ticker else None
        if event.ticker:
            normalized_market = _normalize_upper_optional(event.market)
            if normalized_market == "KR":
                # Force KR names from Naver for consistency.
                fetched_symbol_name = _get_symbol_name_from_yahoo(event.ticker, event.market)
                if fetched_symbol_name:
                    symbol_name = fetched_symbol_name
            elif _is_symbol_like_name(symbol_name, event.ticker, event.market):
                fetched_symbol_name = _get_symbol_name_from_yahoo(event.ticker, event.market)
                if fetched_symbol_name:
                    symbol_name = fetched_symbol_name
        risk_snapshot = open_risk_snapshots.get(
            event.id or -1,
            {"open_risk": 0.0, "open_risk_delta": 0.0, "open_risk_delta_details": None},
        )
        realized_pnl_local_krw = _convert_currency_amount(event.realized_pnl, base_currency, "KRW")
        if realized_pnl_local_krw is None and _normalize_upper_optional(event.currency) == "KRW":
            realized_pnl_local_krw = event.realized_pnl_local
        rows_all.append(
            {
                "id": event.id,
                "ts": event.ts,
                "type": event.type.value,
                "win_lose": (
                    "W"
                    if event.type == EventType.SELL and (event.realized_pnl or 0.0) > 1e-12
                    else (
                        "L"
                        if event.type == EventType.SELL and (event.realized_pnl or 0.0) < -1e-12
                        else ""
                    )
                ),
                "ticker": event.ticker,
                "market": event.market,
                "exchange": event.exchange,
                "currency": event.currency,
                "currency_symbol": _currency_symbol(event.currency),
                "fx_rate_to_base": event.fx_rate_to_base or 1.0,
                "symbol_name": symbol_name,
                "qty": event.qty,
                "price": event.price,
                "price_display": _format_price_for_display(event.price),
                "fee": event.fee,
                "sl": event.sl,
                "tp": event.tp,
                "sl_display": _format_sl_tp_value(event.sl),
                "tp_display": _format_sl_tp_value(event.tp),
                "amount": event_amount(event),
                "realized_pnl": event.realized_pnl,
                "realized_pnl_local": realized_pnl_local_krw,
                "unrealized_pnl": _lookup_unrealized_pnl(
                    unrealized_by_lot_id,
                    unrealized_by_key,
                    event.type,
                    event.lot_id,
                    event.ticker,
                    event.market,
                ),
                "book_asset": book_asset_snapshots.get(event.id or -1, current_book_asset),
                "note": event.note,
                "image_url": event.image_url,
                "image_urls": _split_image_urls(event.image_url),
                "reason": event.reason,
                "review": review_text,
                "trade_group_id": event.trade_group_id,
                "open_risk": risk_snapshot["open_risk"],
                "open_risk_delta": risk_snapshot["open_risk_delta"],
                "open_risk_delta_details": risk_snapshot["open_risk_delta_details"],
            }
        )

    blank_token = "__BLANK__"

    def _normalize_header_filter_values(values: list[str] | None, upper: bool = False) -> set[str]:
        normalized: set[str] = set()
        for raw in values or []:
            text = str(raw or "").strip()
            if not text:
                continue
            if text == blank_token:
                normalized.add(blank_token)
                continue
            normalized.add(text.upper() if upper else text)
        return normalized

    def _row_filter_value(value: Any, upper: bool = False) -> str:
        text = str(value or "").strip()
        if text == "":
            return blank_token
        return text.upper() if upper else text

    def _sort_filter_options(values: set[str]) -> list[str]:
        return sorted(values, key=lambda v: (v != "", v.casefold()))

    filter_options = {
        "ticker": _sort_filter_options({str(row.get("ticker") or "").strip() for row in rows_all}),
        "market": _sort_filter_options({str(row.get("market") or "").strip() for row in rows_all}),
        "currency": _sort_filter_options({str(row.get("currency") or "").strip() for row in rows_all}),
        "symbol_name": _sort_filter_options({str(row.get("symbol_name") or "").strip() for row in rows_all}),
        "type": _sort_filter_options({str(row.get("type") or "").strip() for row in rows_all}),
        "win_lose": _sort_filter_options({str(row.get("win_lose") or "").strip() for row in rows_all}),
    }

    selected_hf_ticker = _normalize_header_filter_values(hf_ticker, upper=True)
    selected_hf_market = _normalize_header_filter_values(hf_market, upper=True)
    selected_hf_currency = _normalize_header_filter_values(hf_currency, upper=True)
    selected_hf_symbol_name = _normalize_header_filter_values(hf_symbol_name, upper=False)
    selected_hf_type = _normalize_header_filter_values(hf_type, upper=True)
    selected_hf_win_lose = _normalize_header_filter_values(hf_win_lose, upper=True)

    rows_filtered = []
    for row in rows_all:
        if selected_hf_ticker and _row_filter_value(row.get("ticker"), upper=True) not in selected_hf_ticker:
            continue
        if selected_hf_market and _row_filter_value(row.get("market"), upper=True) not in selected_hf_market:
            continue
        if selected_hf_currency and _row_filter_value(row.get("currency"), upper=True) not in selected_hf_currency:
            continue
        if selected_hf_symbol_name and _row_filter_value(row.get("symbol_name"), upper=False) not in selected_hf_symbol_name:
            continue
        if selected_hf_type and _row_filter_value(row.get("type"), upper=True) not in selected_hf_type:
            continue
        if selected_hf_win_lose and _row_filter_value(row.get("win_lose"), upper=True) not in selected_hf_win_lose:
            continue
        rows_filtered.append(row)

    filtered_count = len(rows_filtered)
    event_count_ex_sl_update = sum(
        1 for row in rows_filtered if str(row.get("type") or "").upper() != EventType.SL_UPDATE.value
    )
    total_pages = max(1, math.ceil(filtered_count / page_size)) if filtered_count else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    end = start + page_size
    rows = rows_filtered[start:end]
    _attach_sell_vs_peak_metrics(session, rows, sell_alloc_map)

    page_window_start = max(1, page - 2)
    page_window_end = min(total_pages, page + 2)
    page_numbers = list(range(page_window_start, page_window_end + 1))

    return {
        "base_currency": base_currency,
        "base_currency_symbol": _currency_symbol(base_currency),
        "krw_currency_symbol": _currency_symbol("KRW"),
        "usd_currency_symbol": _currency_symbol("USD"),
        "book_asset": current_book_asset,
        "book_asset_mtm": current_book_asset_mtm,
        "book_asset_cost": current_book_asset_cost,
        "book_asset_mtm_dual": _dual_currency_from_base(current_book_asset_mtm, base_currency),
        "book_asset_cost_dual": _dual_currency_from_base(current_book_asset_cost, base_currency),
        "cash_balance": cash_balance,
        "cash_balance_trade": cash_balance_trade,
        "cash_balance_dual": _dual_currency_from_base(cash_balance, base_currency),
        "open_position_mtm": open_position_mtm,
        "open_position_mtm_dual": _dual_currency_from_base(open_position_mtm, base_currency),
        "open_position_cost": open_position_cost,
        "open_position_cost_dual": _dual_currency_from_base(open_position_cost, base_currency),
        "event_count_ex_sl_update": event_count_ex_sl_update,
        "events": rows,
        "total_all_events": len(events),
        "filtered_events": filtered_count,
        "page": page,
        "page_size": page_size,
        "total_events": filtered_count,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < total_pages else None,
        "page_numbers": page_numbers,
        "filters": {
            "q": query or "",
            "event_type": normalized_event_type,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
        "header_filters": {
            "ticker": sorted(selected_hf_ticker),
            "market": sorted(selected_hf_market),
            "currency": sorted(selected_hf_currency),
            "symbol_name": sorted(selected_hf_symbol_name),
            "type": sorted(selected_hf_type),
            "win_lose": sorted(selected_hf_win_lose),
        },
        "filter_options": filter_options,
    }


def _current_open_cost(lot_states: dict[int, dict[str, Any]]) -> float:
    return sum(
        _to_base(state["entry_price"] * state["qty_open"], state.get("fx_rate_to_base"))
        for state in lot_states.values()
        if state["qty_open"] > 0
    )


def _parse_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _quote_symbol_candidates(ticker: str, market: str | None) -> list[str]:
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        return []

    candidates: list[str] = []
    normalized_market = _normalize_upper_optional(market)
    digits = "".join(ch for ch in normalized_ticker if ch.isdigit())

    if normalized_market == "HK":
        base = normalized_ticker[:-3] if normalized_ticker.endswith(".HK") else normalized_ticker
        hk_digits = "".join(ch for ch in base if ch.isdigit())
        if hk_digits:
            canonical = hk_digits.zfill(5) if len(hk_digits) <= 5 else hk_digits
            yahoo_style = canonical[1:] if len(canonical) == 5 and canonical.startswith("0") else canonical
            candidates.append(f"{yahoo_style}.HK")
            candidates.append(f"{canonical}.HK")
            candidates.append(f"{hk_digits}.HK")
        if normalized_ticker.endswith(".HK"):
            candidates.append(normalized_ticker)
        elif "." not in normalized_ticker:
            candidates.append(f"{normalized_ticker}.HK")
    elif normalized_market == "KR":
        if normalized_ticker.endswith(".KS") or normalized_ticker.endswith(".KQ"):
            candidates.append(normalized_ticker)
        if digits:
            code = digits.zfill(6)
            candidates.append(f"{code}.KS")
            candidates.append(f"{code}.KQ")
        if "." not in normalized_ticker:
            candidates.append(f"{normalized_ticker}.KS")
            candidates.append(f"{normalized_ticker}.KQ")
        candidates.append(normalized_ticker)
    else:
        candidates.append(normalized_ticker)

    unique: list[str] = []
    seen: set[str] = set()
    for symbol in candidates:
        if symbol in seen:
            continue
        seen.add(symbol)
        unique.append(symbol)
    return unique


def _fetch_json_with_browser_headers(url: str, timeout: int = 8) -> dict[str, Any] | None:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _extract_symbol_name_from_payload(payload: dict[str, Any]) -> str | None:
    # v7/quote response path
    quote_response = payload.get("quoteResponse") if isinstance(payload, dict) else None
    results = quote_response.get("result") if isinstance(quote_response, dict) else None
    if isinstance(results, list) and results:
        first = results[0] if isinstance(results[0], dict) else {}
        for key in ("longName", "shortName", "displayName"):
            value = _normalize_optional_text(first.get(key))
            if value:
                return value

    # v10/quoteSummary response path
    qsum = payload.get("quoteSummary") if isinstance(payload, dict) else None
    qsum_results = qsum.get("result") if isinstance(qsum, dict) else None
    if isinstance(qsum_results, list) and qsum_results:
        first = qsum_results[0] if isinstance(qsum_results[0], dict) else {}
        price = first.get("price") if isinstance(first, dict) else None
        if isinstance(price, dict):
            for key in ("longName", "shortName", "displayName"):
                value = _normalize_optional_text(price.get(key))
                if value:
                    return value

    # v8/chart response path
    chart = payload.get("chart") if isinstance(payload, dict) else None
    chart_results = chart.get("result") if isinstance(chart, dict) else None
    if isinstance(chart_results, list) and chart_results:
        first = chart_results[0] if isinstance(chart_results[0], dict) else {}
        meta = first.get("meta") if isinstance(first, dict) else None
        if isinstance(meta, dict):
            for key in ("longName", "shortName"):
                value = _normalize_optional_text(meta.get(key))
                if value:
                    return value

    return None


def _fetch_symbol_name_from_yahoo_symbol(symbol: str) -> str | None:
    encoded = quote(symbol, safe="")
    urls = [
        f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={encoded}",
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{encoded}?modules=price",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d",
    ]
    for url in urls:
        payload = _fetch_json_with_browser_headers(url, timeout=8)
        if not payload:
            continue
        name = _extract_symbol_name_from_payload(payload)
        if name:
            return name
    return None


def _fetch_symbol_name_from_naver_kr(ticker: str) -> str | None:
    digits = "".join(ch for ch in (ticker or "") if ch.isdigit()).zfill(6)
    if len(digits) != 6:
        return None
    url = f"https://finance.naver.com/item/main.naver?code={digits}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    try:
        with urlopen(req, timeout=8) as response:
            raw = response.read()
    except Exception:
        return None

    decoded = None
    for encoding in ("euc-kr", "cp949", "utf-8"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        return None

    # Prefer og:title first because page layout can change.
    m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', decoded, re.IGNORECASE)
    if m:
        candidate = html.unescape(m.group(1)).strip()
        candidate = candidate.replace(" - Npay 증권", "").replace(" - 네이버페이 증권", "")
        candidate = candidate.split(" : ", 1)[0].strip()
        if candidate:
            return candidate

    m2 = re.search(r'class=["\']wrap_company["\'][\s\S]*?<a[^>]*>([^<]+)</a>', decoded, re.IGNORECASE)
    if m2:
        candidate = html.unescape(m2.group(1)).strip()
        if candidate:
            return candidate
    return None


def _fetch_latest_quote_from_naver_kr(ticker: str) -> float | None:
    digits = "".join(ch for ch in (ticker or "") if ch.isdigit()).zfill(6)
    if len(digits) != 6:
        return None
    url = f"https://finance.naver.com/item/main.naver?code={digits}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    try:
        with urlopen(req, timeout=8) as response:
            raw = response.read()
    except Exception:
        return None

    decoded = None
    for encoding in ("euc-kr", "cp949", "utf-8"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        return None

    m = re.search(
        r'class=["\']no_today["\'][\s\S]*?<span class=["\']blind["\']>([0-9,]+)</span>',
        decoded,
        re.IGNORECASE,
    )
    if not m:
        return None
    numeric = m.group(1).replace(",", "").strip()
    return _parse_positive_float(numeric)


def _is_symbol_like_name(name: str | None, ticker: str | None, market: str | None) -> bool:
    n = (name or "").strip()
    t = (ticker or "").strip().upper()
    if not n:
        return True
    if not t:
        return False
    nu = n.upper()
    if nu == t:
        return True
    digits = "".join(ch for ch in t if ch.isdigit())
    symbol_candidates = {t}
    for symbol in _quote_symbol_candidates(t, market):
        symbol_candidates.add(symbol.strip().upper())
    if digits:
        symbol_candidates.add(digits)
        if len(digits) <= 5:
            canonical_hk = digits.zfill(5)
            symbol_candidates.add(canonical_hk)
            if canonical_hk.startswith("0"):
                symbol_candidates.add(canonical_hk[1:])
    if nu in symbol_candidates:
        return True
    if _normalize_upper_optional(market) == "KR" and ("NPAY 증권" in nu or "네이버페이 증권" in n):
        return True
    return False


def _should_use_naver_kr_source(ticker: str, market: str | None) -> bool:
    normalized_ticker = (ticker or "").strip().upper()
    normalized_market = _normalize_upper_optional(market)
    if normalized_market == "KR":
        return True
    if normalized_ticker.endswith(".KS") or normalized_ticker.endswith(".KQ"):
        return True
    if normalized_market is None and re.fullmatch(r"\d{6}", normalized_ticker):
        return True
    return False


def _get_symbol_name_from_yahoo(ticker: str, market: str | None) -> str | None:
    now_ts = datetime.utcnow().timestamp()
    normalized_ticker = (ticker or "").strip().upper()

    if _should_use_naver_kr_source(normalized_ticker, market):
        naver_cache_key = f"NAVER:{normalized_ticker}"
        cached_naver = _name_cache.get(naver_cache_key)
        if cached_naver and now_ts - cached_naver["fetched_at"] < NAME_CACHE_TTL_SECONDS:
            return cached_naver["name"]
        naver_name = _fetch_symbol_name_from_naver_kr(normalized_ticker)
        if naver_name:
            _name_cache[naver_cache_key] = {"fetched_at": now_ts, "name": naver_name}
            return naver_name
        if _normalize_upper_optional(market) == "KR":
            # Explicit KR market must use Naver as the source of truth for names.
            return None

    for symbol in _quote_symbol_candidates(ticker, market):
        cached = _name_cache.get(symbol)
        if cached and now_ts - cached["fetched_at"] < NAME_CACHE_TTL_SECONDS:
            return cached["name"]

        fetched_name = _fetch_symbol_name_from_yahoo_symbol(symbol)
        if not fetched_name:
            continue
        normalized_name = fetched_name.strip().upper()
        if normalized_name in {symbol.strip().upper(), normalized_ticker}:
            # Symbol-like value is not a human-readable company name; keep trying.
            continue
        _name_cache[symbol] = {"fetched_at": now_ts, "name": fetched_name}
        return fetched_name
    return None


def _fetch_latest_quote_from_yfinance_symbol(symbol: str) -> float | None:
    # Prefer direct Yahoo chart API so runtime does not depend on yfinance package.
    yahoo_url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=5d&interval=1d&includePrePost=false&events=div%2Csplits"
    )
    try:
        with urlopen(yahoo_url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        chart = payload.get("chart") if isinstance(payload, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if isinstance(results, list) and results:
            first = results[0] if isinstance(results[0], dict) else {}
            meta = first.get("meta") if isinstance(first, dict) else None
            if isinstance(meta, dict):
                for key in ("regularMarketPrice", "previousClose"):
                    parsed = _parse_positive_float(meta.get(key))
                    if parsed is not None:
                        return parsed
            indicators = first.get("indicators") if isinstance(first, dict) else None
            if isinstance(indicators, dict):
                quotes = indicators.get("quote")
                if isinstance(quotes, list) and quotes:
                    quote0 = quotes[0] if isinstance(quotes[0], dict) else {}
                    closes = quote0.get("close")
                    if isinstance(closes, list):
                        for value in reversed(closes):
                            parsed = _parse_positive_float(value)
                            if parsed is not None:
                                return parsed
    except Exception:
        pass

    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return None

    try:
        ticker_obj = yf.Ticker(symbol)
        fast_info = getattr(ticker_obj, "fast_info", None)
        if fast_info is not None:
            for key in ("lastPrice", "last_price", "regularMarketPrice", "previousClose"):
                value = fast_info.get(key) if hasattr(fast_info, "get") else getattr(fast_info, key, None)
                parsed = _parse_positive_float(value)
                if parsed is not None:
                    return parsed

        hist = ticker_obj.history(period="5d", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            closes = hist["Close"].dropna()
            if not closes.empty:
                return _parse_positive_float(closes.iloc[-1])
    except Exception:
        return None

    return None


def _get_latest_quote_price(ticker: str, market: str | None) -> float | None:
    now_ts = datetime.utcnow().timestamp()
    normalized_ticker = (ticker or "").strip().upper()

    if _should_use_naver_kr_source(normalized_ticker, market):
        naver_price_key = f"NAVER_PRICE:{normalized_ticker}"
        cached_naver = _quote_cache.get(naver_price_key)
        if cached_naver and now_ts - cached_naver["fetched_at"] < QUOTE_CACHE_TTL_SECONDS:
            return cached_naver["price"]
        naver_price = _fetch_latest_quote_from_naver_kr(normalized_ticker)
        if naver_price is not None:
            _quote_cache[naver_price_key] = {"fetched_at": now_ts, "price": naver_price}
            return naver_price

    for symbol in _quote_symbol_candidates(ticker, market):
        cached = _quote_cache.get(symbol)
        if cached and now_ts - cached["fetched_at"] < QUOTE_CACHE_TTL_SECONDS:
            return cached["price"]

        latest_price = _fetch_latest_quote_from_yfinance_symbol(symbol)
        if latest_price is None:
            continue
        _quote_cache[symbol] = {"fetched_at": now_ts, "price": latest_price}
        return latest_price
    return None


def _cache_latest_info(cache: dict[str, dict[str, Any]]) -> tuple[int, str | None, int | None]:
    count = len(cache)
    if count == 0:
        return 0, None, None
    latest_ts = max(float(entry.get("fetched_at", 0.0) or 0.0) for entry in cache.values())
    if latest_ts <= 0:
        return count, None, None
    latest_dt = datetime.utcfromtimestamp(latest_ts)
    age_sec = int(max(0.0, datetime.utcnow().timestamp() - latest_ts))
    return count, latest_dt.isoformat() + "Z", age_sec


def get_market_data_cache_status() -> dict[str, Any]:
    quote_count, quote_latest_at, quote_age_sec = _cache_latest_info(_quote_cache)
    fx_count, fx_latest_at, fx_age_sec = _cache_latest_info(_fx_cache)
    name_count, name_latest_at, name_age_sec = _cache_latest_info(_name_cache)
    return {
        "quote_entries": quote_count,
        "quote_latest_at": quote_latest_at,
        "quote_latest_age_sec": quote_age_sec,
        "fx_entries": fx_count,
        "fx_latest_at": fx_latest_at,
        "fx_latest_age_sec": fx_age_sec,
        "name_entries": name_count,
        "name_latest_at": name_latest_at,
        "name_latest_age_sec": name_age_sec,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def refresh_market_data_cache(clear_name_cache: bool = False) -> dict[str, Any]:
    quote_before = len(_quote_cache)
    fx_before = len(_fx_cache)
    name_before = len(_name_cache)
    _quote_cache.clear()
    _fx_cache.clear()
    if clear_name_cache:
        _name_cache.clear()
    return {
        "ok": True,
        "cleared_quote_entries": quote_before,
        "cleared_fx_entries": fx_before,
        "cleared_name_entries": name_before if clear_name_cache else 0,
        "clear_name_cache": clear_name_cache,
        "refreshed_at": datetime.utcnow().isoformat() + "Z",
        "status": get_market_data_cache_status(),
    }


def _current_open_market_value(session: Session) -> float:
    lots = session.exec(select(Lot).where(Lot.qty_open > 0)).all()
    if not lots:
        return 0.0

    by_key: dict[tuple[str, str | None], list[Lot]] = defaultdict(list)
    for lot in lots:
        ticker = (lot.ticker or "").strip().upper()
        if not ticker:
            continue
        by_key[(ticker, _normalize_upper_optional(lot.market))].append(lot)

    total_value = 0.0
    for (ticker, market), key_lots in by_key.items():
        latest_price = _get_latest_quote_price(ticker, market)
        for lot in key_lots:
            qty_open = lot.qty_open or 0.0
            fx_rate = lot.fx_rate_to_base or 1.0
            price_for_value = latest_price if latest_price is not None else (lot.entry_price or 0.0)
            total_value += price_for_value * qty_open * fx_rate
    return total_value


def _build_open_unrealized_pnl_maps(
    session: Session,
) -> tuple[dict[int, float], dict[tuple[str, str | None], float]]:
    lots = session.exec(select(Lot).where(Lot.qty_open > 0)).all()
    by_key: dict[tuple[str, str | None], list[Lot]] = defaultdict(list)
    for lot in lots:
        ticker = (lot.ticker or "").strip().upper()
        if not ticker:
            continue
        by_key[(ticker, _normalize_upper_optional(lot.market))].append(lot)

    by_lot_id: dict[int, float] = {}
    by_ticker_market: dict[tuple[str, str | None], float] = {}
    for (ticker, market), key_lots in by_key.items():
        latest_price = _get_latest_quote_price(ticker, market)
        if latest_price is None:
            continue
        key_total = 0.0
        for lot in key_lots:
            entry_price = lot.entry_price or 0.0
            qty_open = lot.qty_open or 0.0
            fx_rate = lot.fx_rate_to_base or 1.0
            lot_pnl = (latest_price - entry_price) * qty_open * fx_rate
            if lot.id is not None:
                by_lot_id[lot.id] = lot_pnl
            key_total += lot_pnl
        by_ticker_market[(ticker, market)] = key_total
    return by_lot_id, by_ticker_market


def _lookup_unrealized_pnl(
    unrealized_by_lot_id: dict[int, float],
    unrealized_by_key: dict[tuple[str, str | None], float],
    event_type: EventType,
    lot_id: int | None,
    ticker: str | None,
    market: str | None,
) -> float | None:
    if event_type == EventType.BUY and lot_id is not None:
        lot_value = unrealized_by_lot_id.get(lot_id)
        if lot_value is not None:
            return lot_value
    normalized_ticker = (ticker or "").strip().upper()
    if not normalized_ticker:
        return None
    normalized_market = _normalize_upper_optional(market)
    direct = unrealized_by_key.get((normalized_ticker, normalized_market))
    if direct is not None:
        return direct
    if normalized_market is None:
        matches = [v for (t, _m), v in unrealized_by_key.items() if t == normalized_ticker]
        if len(matches) == 1:
            return matches[0]
    return None


def _build_sell_alloc_map(session: Session, sell_event_ids: list[int]) -> dict[int, list[SellAllocation]]:
    alloc_map: dict[int, list[SellAllocation]] = defaultdict(list)
    if not sell_event_ids:
        return alloc_map

    allocations = session.exec(
        select(SellAllocation)
        .where(SellAllocation.sell_event_id.in_(sell_event_ids))
        .order_by(SellAllocation.id.asc())
    ).all()
    for alloc in allocations:
        alloc_map[alloc.sell_event_id].append(alloc)
    return alloc_map


def _build_event_timeline(session: Session) -> list[dict[str, Any]]:
    events = session.exec(select(Event).order_by(Event.ts.asc(), Event.id.asc())).all()
    sell_event_ids = [event.id for event in events if event.type == EventType.SELL and event.id is not None]
    sell_alloc_map = _build_sell_alloc_map(session, [x for x in sell_event_ids if x is not None])

    lot_states: dict[int, dict[str, Any]] = {}
    cash_balance = 0.0
    has_cashflow_events = _has_cashflow_events(session)
    timeline: list[dict[str, Any]] = []

    for event in events:
        cashflow_delta = 0.0
        trade_count_delta = 0
        realized_pnl_delta = 0.0
        realized_cost_basis_delta = 0.0
        sell_count_delta = 0
        sell_non_be_count_delta = 0
        sell_be_count_delta = 0
        sell_win_count_delta = 0
        open_cost_before = _current_open_cost(lot_states)
        asset_before = (cash_balance + open_cost_before) if has_cashflow_events else open_cost_before

        if event.type == EventType.CASHFLOW:
            cashflow_delta = event.cash_amount or 0.0
            cash_balance += cashflow_delta

        elif event.type == EventType.BUY:
            qty = event.qty or 0.0
            price = event.price or 0.0
            fee = event.fee or 0.0
            cash_balance -= _to_base((qty * price + fee), event.fx_rate_to_base)
            trade_count_delta = 1

            if event.lot_id is not None:
                lot_states[event.lot_id] = {
                    "entry_price": price,
                    "qty_open": qty,
                    "sl": event.sl,
                    "tp": event.tp,
                    "market": event.market,
                    "exchange": event.exchange,
                    "currency": event.currency,
                    "fx_rate_to_base": event.fx_rate_to_base or 1.0,
                }

        elif event.type == EventType.SELL:
            qty = event.qty or 0.0
            price = event.price or 0.0
            fee = event.fee or 0.0
            cash_balance += _to_base((qty * price - fee), event.fx_rate_to_base)
            trade_count_delta = 1
            sell_count_delta = 1
            realized_pnl_delta = event.realized_pnl or 0.0
            if _is_breakeven_sell(realized_pnl_delta, event.reason):
                sell_be_count_delta = 1
            else:
                sell_non_be_count_delta = 1
                if realized_pnl_delta > 0:
                    sell_win_count_delta = 1

            if event.id is not None:
                for alloc in sell_alloc_map.get(event.id, []):
                    lot_state = lot_states.get(alloc.lot_id)
                    if lot_state is None:
                        continue
                    realized_cost_basis_delta += _to_base(
                        (lot_state.get("entry_price", 0.0) or 0.0) * alloc.qty_sold,
                        lot_state.get("fx_rate_to_base", 1.0) or 1.0,
                    )
                    lot_state["qty_open"] = max(0.0, lot_state["qty_open"] - alloc.qty_sold)

        elif event.type == EventType.SL_UPDATE:
            if event.lot_id is not None and event.lot_id in lot_states:
                lot_states[event.lot_id]["sl"] = event.sl
                lot_states[event.lot_id]["tp"] = event.tp

        open_cost_after = _current_open_cost(lot_states)
        asset_after = (cash_balance + open_cost_after) if has_cashflow_events else open_cost_after
        timeline.append(
            {
                "event_id": event.id,
                "ts": event.ts,
                "type": event.type.value,
                "asset_before": asset_before,
                "asset_after": asset_after,
                "cashflow_delta": cashflow_delta,
                "trade_count_delta": trade_count_delta,
                "realized_pnl_delta": realized_pnl_delta,
                "realized_cost_basis_delta": realized_cost_basis_delta,
                "sell_count_delta": sell_count_delta,
                "sell_non_be_count_delta": sell_non_be_count_delta,
                "sell_be_count_delta": sell_be_count_delta,
                "sell_win_count_delta": sell_win_count_delta,
            }
        )

    return timeline


def _period_info(ts: datetime, granularity: str) -> tuple[str, str, date, date]:
    d = ts.date()
    if granularity == "daily":
        period_start = d
        period_end = d
        key = d.isoformat()
        label = key
        return key, label, period_start, period_end

    if granularity == "weekly":
        iso_year, iso_week, _ = d.isocalendar()
        period_start = date.fromisocalendar(iso_year, iso_week, 1)
        period_end = period_start + timedelta(days=6)
        key = f"{iso_year}-W{iso_week:02d}"
        label = f"{key} ({period_start.isoformat()} ~ {period_end.isoformat()})"
        return key, label, period_start, period_end

    if granularity == "monthly":
        period_start = date(d.year, d.month, 1)
        if d.month == 12:
            next_month = date(d.year + 1, 1, 1)
        else:
            next_month = date(d.year, d.month + 1, 1)
        period_end = next_month - timedelta(days=1)
        key = f"{d.year:04d}-{d.month:02d}"
        label = f"{key} ({period_start.isoformat()} ~ {period_end.isoformat()})"
        return key, label, period_start, period_end

    if granularity == "yearly":
        period_start = date(d.year, 1, 1)
        period_end = date(d.year, 12, 31)
        key = f"{d.year:04d}"
        label = f"{key} ({period_start.isoformat()} ~ {period_end.isoformat()})"
        return key, label, period_start, period_end

    raise ValueError(f"Unsupported granularity: {granularity}")


def _calc_mdd_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    mdd_pct = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown_pct = (peak - value) / peak * 100
            if drawdown_pct > mdd_pct:
                mdd_pct = drawdown_pct
    return mdd_pct


def _build_period_stats(timeline: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for point in timeline:
        key, label, period_start, period_end = _period_info(point["ts"], granularity)
        row = grouped.get(key)
        if row is None:
            total_days = (period_end - period_start).days + 1
            row = {
                "period_key": key,
                "period_label": label,
                "period_start": period_start,
                "period_end": period_end,
                "total_days": total_days,
                "trade_count": 0,
                "sell_count": 0,
                "sell_non_be_count": 0,
                "sell_be_count": 0,
                "sell_win_count": 0,
                "net_cashflow": 0.0,
                "deposit_sum": 0.0,
                "withdraw_sum": 0.0,
                "weighted_deposit_sum": 0.0,
                "weighted_withdraw_sum": 0.0,
                "realized_pnl": 0.0,
                "realized_cost_basis": 0.0,
                "asset_start": point["asset_before"],
                "asset_end": point["asset_after"],
                "equity_curve": [point["asset_before"], point["asset_after"]],
            }
            grouped[key] = row
        else:
            row["asset_end"] = point["asset_after"]
            row["equity_curve"].append(point["asset_after"])

        row["trade_count"] += point["trade_count_delta"]
        row["sell_count"] += point["sell_count_delta"]
        row["sell_non_be_count"] += point["sell_non_be_count_delta"]
        row["sell_be_count"] += point["sell_be_count_delta"]
        row["sell_win_count"] += point["sell_win_count_delta"]
        row["net_cashflow"] += point["cashflow_delta"]
        row["realized_pnl"] += point["realized_pnl_delta"]
        row["realized_cost_basis"] += point.get("realized_cost_basis_delta", 0.0)

        cashflow_delta = point["cashflow_delta"]
        if cashflow_delta != 0:
            event_date = point["ts"].date()
            remaining_days = (row["period_end"] - event_date).days + 1
            if remaining_days < 0:
                remaining_days = 0
            weight = remaining_days / row["total_days"] if row["total_days"] > 0 else 0

            if cashflow_delta > 0:
                row["deposit_sum"] += cashflow_delta
                row["weighted_deposit_sum"] += cashflow_delta * weight
            else:
                withdrawal_abs = abs(cashflow_delta)
                row["withdraw_sum"] += withdrawal_abs
                row["weighted_withdraw_sum"] += withdrawal_abs * weight

    stats: list[dict[str, Any]] = []
    for row in grouped.values():
        asset_start = row["asset_start"]
        asset_end = row["asset_end"]
        profit_amount = asset_end - asset_start + row["withdraw_sum"] - row["deposit_sum"]

        if abs(asset_start) > RETURN_DENOMINATOR_MIN_BASE:
            return_method1_pct = profit_amount / asset_start * 100
        else:
            return_method1_pct = None

        weighted_capital_base = (
            asset_start + row["weighted_deposit_sum"] - row["weighted_withdraw_sum"]
        )
        if abs(weighted_capital_base) > RETURN_DENOMINATOR_MIN_BASE:
            return_method2_pct = profit_amount / weighted_capital_base * 100
        else:
            return_method2_pct = None

        sell_count = row["sell_count"]
        sell_non_be_count = row["sell_non_be_count"]
        sell_be_count = row["sell_be_count"]
        win_rate_pct = (row["sell_win_count"] / sell_non_be_count * 100) if sell_non_be_count > 0 else None
        be_rate_pct = (sell_be_count / sell_count * 100) if sell_count > 0 else None
        avg_realized_pnl = (row["realized_pnl"] / sell_count) if sell_count > 0 else None
        realized_return_pct = (
            (row["realized_pnl"] / row["realized_cost_basis"] * 100)
            if abs(row["realized_cost_basis"]) > 1e-12
            else None
        )

        stats.append(
            {
                "period_key": row["period_key"],
                "period_label": row["period_label"],
                "period_start": row["period_start"].isoformat(),
                "period_end": row["period_end"].isoformat(),
                "trade_count": row["trade_count"],
                "sell_count": row["sell_count"],
                "sell_non_be_count": sell_non_be_count,
                "sell_be_count": sell_be_count,
                "win_rate_pct": win_rate_pct,
                "be_rate_pct": be_rate_pct,
                "mdd_pct": _calc_mdd_pct(row["equity_curve"]),
                "return_method1_pct": return_method1_pct,
                "return_method2_pct": return_method2_pct,
                "realized_return_pct": realized_return_pct,
                "realized_pnl": row["realized_pnl"],
                "realized_cost_basis": row["realized_cost_basis"],
                "avg_realized_pnl_per_sell": avg_realized_pnl,
                "net_cashflow": row["net_cashflow"],
                "deposit_sum": row["deposit_sum"],
                "withdraw_sum": row["withdraw_sum"],
                "weighted_deposit_sum": row["weighted_deposit_sum"],
                "weighted_withdraw_sum": row["weighted_withdraw_sum"],
                "asset_start": asset_start,
                "asset_end": asset_end,
                "profit_amount": profit_amount,
                "weighted_capital_base": weighted_capital_base,
            }
        )

    stats.sort(key=lambda x: x["period_start"], reverse=True)
    return stats


def _build_closed_trade_rows(session: Session, closed_sell_events: list[Event]) -> list[dict[str, Any]]:
    sell_event_ids = [event.id for event in closed_sell_events if event.id is not None]
    if not sell_event_ids:
        return []

    allocs = session.exec(
        select(SellAllocation)
        .where(SellAllocation.sell_event_id.in_(sell_event_ids))
        .order_by(SellAllocation.sell_event_id.asc(), SellAllocation.id.asc())
    ).all()
    allocs_by_event: dict[int, list[SellAllocation]] = defaultdict(list)
    lot_ids: set[int] = set()
    for alloc in allocs:
        allocs_by_event[alloc.sell_event_id].append(alloc)
        lot_ids.add(alloc.lot_id)

    lot_map: dict[int, Lot] = {}
    if lot_ids:
        lots = session.exec(select(Lot).where(Lot.id.in_(list(lot_ids)))).all()
        lot_map = {lot.id: lot for lot in lots if lot.id is not None}

    rows: list[dict[str, Any]] = []
    for event in closed_sell_events:
        if event.id is None:
            continue
        realized = event.realized_pnl
        if realized is None:
            continue
        try:
            realized_value = float(realized)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(realized_value):
            continue

        event_allocs = allocs_by_event.get(event.id, [])
        qty_sold = 0.0
        cost_basis_base = 0.0
        hold_days_weighted_sum = 0.0
        hold_days_weighted_qty = 0.0
        for alloc in event_allocs:
            lot = lot_map.get(alloc.lot_id)
            if lot is None:
                continue
            qty = float(alloc.qty_sold or 0.0)
            if qty <= 0:
                continue
            qty_sold += qty
            lot_fx = lot.fx_rate_to_base if (lot.fx_rate_to_base and lot.fx_rate_to_base > 0) else (event.fx_rate_to_base or 1.0)
            cost_basis_base += _to_base((lot.entry_price or 0.0) * qty, lot_fx)
            try:
                held_days = (event.ts - lot.opened_at).total_seconds() / 86400.0
            except Exception:
                held_days = 0.0
            if not math.isfinite(held_days):
                held_days = 0.0
            if held_days < 0:
                held_days = 0.0
            hold_days_weighted_sum += held_days * qty
            hold_days_weighted_qty += qty

        return_pct = (realized_value / cost_basis_base * 100.0) if cost_basis_base > 1e-12 else None
        hold_days = (
            hold_days_weighted_sum / hold_days_weighted_qty
            if hold_days_weighted_qty > 1e-12
            else None
        )
        rows.append(
            {
                "event_id": event.id,
                "ts": event.ts.isoformat(),
                "ticker": event.ticker,
                "market": event.market,
                "currency": event.currency,
                "qty_sold": qty_sold,
                "cost_basis_base": cost_basis_base,
                "realized_pnl": realized_value,
                "return_pct": return_pct,
                "hold_days": hold_days,
            }
        )

    return rows


def _build_monthly_check_rows(closed_trade_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not closed_trade_rows:
        return [], {
            "trade_count": 0,
            "avg_profit_pct": None,
            "avg_loss_pct": None,
            "win_rate_pct": None,
            "success_failure_ratio": None,
            "adjusted_success_failure_ratio": None,
            "max_profit_pct": None,
            "max_loss_pct": None,
            "avg_win_hold_days": None,
            "avg_loss_hold_days": None,
        }

    parsed: list[dict[str, Any]] = []
    for row in closed_trade_rows:
        try:
            ts = datetime.fromisoformat(str(row.get("ts") or ""))
        except Exception:
            continue
        return_pct = row.get("return_pct")
        try:
            return_value = float(return_pct) if return_pct is not None else None
        except (TypeError, ValueError):
            return_value = None
        if return_value is not None and not math.isfinite(return_value):
            return_value = None
        hold_days_raw = row.get("hold_days")
        try:
            hold_days = float(hold_days_raw) if hold_days_raw is not None else None
        except (TypeError, ValueError):
            hold_days = None
        if hold_days is not None and not math.isfinite(hold_days):
            hold_days = None
        parsed.append(
            {
                "ts": ts,
                "return_pct": return_value,
                "hold_days": hold_days,
            }
        )

    if not parsed:
        return [], {
            "trade_count": 0,
            "avg_profit_pct": None,
            "avg_loss_pct": None,
            "win_rate_pct": None,
            "success_failure_ratio": None,
            "adjusted_success_failure_ratio": None,
            "max_profit_pct": None,
            "max_loss_pct": None,
            "avg_win_hold_days": None,
            "avg_loss_hold_days": None,
        }

    parsed.sort(key=lambda x: x["ts"])

    def _month_start(d: date) -> date:
        return date(d.year, d.month, 1)

    def _next_month(d: date) -> date:
        if d.month == 12:
            return date(d.year + 1, 1, 1)
        return date(d.year, d.month + 1, 1)

    start_month = _month_start(parsed[0]["ts"].date())
    end_month = _month_start(parsed[-1]["ts"].date())

    month_rows: list[date] = []
    cursor = start_month
    while cursor <= end_month:
        month_rows.append(cursor)
        cursor = _next_month(cursor)

    grouped: dict[str, dict[str, Any]] = {}
    for month_start in month_rows:
        key = month_start.isoformat()
        grouped[key] = {
            "period_key": month_start.strftime("%Y-%m"),
            "period_start": key,
            "trade_count": 0,
            "wins": [],
            "losses": [],
            "win_holds": [],
            "loss_holds": [],
        }

    for row in parsed:
        m = _month_start(row["ts"].date())
        key = m.isoformat()
        bucket = grouped.get(key)
        if bucket is None:
            continue
        bucket["trade_count"] += 1
        value = row["return_pct"]
        hold_days = row["hold_days"]
        if value is None:
            continue
        if value > 1e-12:
            bucket["wins"].append(value)
            if hold_days is not None:
                bucket["win_holds"].append(hold_days)
        elif value < -1e-12:
            bucket["losses"].append(abs(value))
            if hold_days is not None:
                bucket["loss_holds"].append(hold_days)

    def _safe_mean(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    output_rows: list[dict[str, Any]] = []
    all_wins: list[float] = []
    all_losses: list[float] = []
    all_win_holds: list[float] = []
    all_loss_holds: list[float] = []
    total_trade_count = 0
    total_win_count = 0

    for month_start in month_rows:
        key = month_start.isoformat()
        bucket = grouped[key]
        trade_count = int(bucket["trade_count"])
        wins = [float(x) for x in bucket["wins"]]
        losses = [float(x) for x in bucket["losses"]]
        win_holds = [float(x) for x in bucket["win_holds"]]
        loss_holds = [float(x) for x in bucket["loss_holds"]]
        win_count = len(wins)
        win_rate_pct = (win_count / trade_count * 100.0) if trade_count > 0 else None
        avg_profit_pct = _safe_mean(wins)
        avg_loss_pct = _safe_mean(losses)
        success_failure_ratio = (
            (avg_profit_pct / avg_loss_pct)
            if avg_profit_pct is not None and avg_loss_pct is not None and avg_loss_pct > 1e-12
            else None
        )
        adjusted_success_failure_ratio = None
        if (
            win_rate_pct is not None
            and avg_profit_pct is not None
            and avg_loss_pct is not None
            and avg_loss_pct > 1e-12
            and win_rate_pct < 100.0
        ):
            p_win = max(0.0, min(1.0, win_rate_pct / 100.0))
            p_loss = 1.0 - p_win
            if p_loss > 1e-12:
                adjusted_success_failure_ratio = (p_win * avg_profit_pct) / (p_loss * avg_loss_pct)

        max_profit_pct = max(wins) if wins else None
        max_loss_pct = max(losses) if losses else None
        avg_win_hold_days = _safe_mean(win_holds)
        avg_loss_hold_days = _safe_mean(loss_holds)

        output_rows.append(
            {
                "period_key": bucket["period_key"],
                "month_label": month_start.strftime("%Y-%m"),
                "trade_count": trade_count,
                "avg_profit_pct": avg_profit_pct,
                "avg_loss_pct": avg_loss_pct,
                "win_rate_pct": win_rate_pct,
                "success_failure_ratio": success_failure_ratio,
                "adjusted_success_failure_ratio": adjusted_success_failure_ratio,
                "max_profit_pct": max_profit_pct,
                "max_loss_pct": max_loss_pct,
                "avg_win_hold_days": avg_win_hold_days,
                "avg_loss_hold_days": avg_loss_hold_days,
            }
        )

        total_trade_count += trade_count
        total_win_count += win_count
        all_wins.extend(wins)
        all_losses.extend(losses)
        all_win_holds.extend(win_holds)
        all_loss_holds.extend(loss_holds)

    avg_profit_all = _safe_mean(all_wins)
    avg_loss_all = _safe_mean(all_losses)
    win_rate_all = (total_win_count / total_trade_count * 100.0) if total_trade_count > 0 else None
    success_failure_all = (
        (avg_profit_all / avg_loss_all)
        if avg_profit_all is not None and avg_loss_all is not None and avg_loss_all > 1e-12
        else None
    )
    adjusted_success_failure_all = None
    if (
        win_rate_all is not None
        and avg_profit_all is not None
        and avg_loss_all is not None
        and avg_loss_all > 1e-12
        and win_rate_all < 100.0
    ):
        p_win_all = max(0.0, min(1.0, win_rate_all / 100.0))
        p_loss_all = 1.0 - p_win_all
        if p_loss_all > 1e-12:
            adjusted_success_failure_all = (p_win_all * avg_profit_all) / (p_loss_all * avg_loss_all)

    summary = {
        "trade_count": total_trade_count,
        "avg_profit_pct": avg_profit_all,
        "avg_loss_pct": avg_loss_all,
        "win_rate_pct": win_rate_all,
        "success_failure_ratio": success_failure_all,
        "adjusted_success_failure_ratio": adjusted_success_failure_all,
        "max_profit_pct": max(all_wins) if all_wins else None,
        "max_loss_pct": max(all_losses) if all_losses else None,
        "avg_win_hold_days": _safe_mean(all_win_holds),
        "avg_loss_hold_days": _safe_mean(all_loss_holds),
    }
    return output_rows, summary


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _parse_year_month(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if len(text) < 7:
        return None
    try:
        dt = datetime.strptime(text[:7], "%Y-%m")
    except ValueError:
        return None
    return date(dt.year, dt.month, 1)


def _empty_monthly_check_row(month_label: str) -> dict[str, Any]:
    return {
        "period_key": month_label,
        "month_label": month_label,
        "trade_count": 0,
        "avg_profit_pct": None,
        "avg_loss_pct": None,
        "win_rate_pct": None,
        "success_failure_ratio": None,
        "adjusted_success_failure_ratio": None,
        "max_profit_pct": None,
        "max_loss_pct": None,
        "avg_win_hold_days": None,
        "avg_loss_hold_days": None,
    }


def build_monthly_check_page(session: Session) -> dict[str, Any]:
    stats = build_stats(session)
    raw_rows = stats.get("monthly_check_rows") or []
    summary = stats.get("monthly_check_summary") or {}

    row_map: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        month_label_raw = raw.get("month_label") or raw.get("period_key")
        month_date = _parse_year_month(str(month_label_raw) if month_label_raw is not None else None)
        if month_date is None:
            continue
        month_label = month_date.strftime("%Y-%m")
        merged = _empty_monthly_check_row(month_label)
        merged.update(raw)
        merged["month_label"] = month_label
        merged["period_key"] = month_label
        row_map[month_label] = merged

    latest_event_ts = session.exec(select(Event.ts).order_by(Event.ts.desc())).first()
    if isinstance(latest_event_ts, datetime):
        end_month = _month_start(latest_event_ts.date())
    elif row_map:
        end_month = max(_parse_year_month(key) for key in row_map if _parse_year_month(key) is not None)
        end_month = end_month if isinstance(end_month, date) else MONTHLY_CHECK_START_MONTH
    else:
        end_month = _month_start(date.today())

    start_month = MONTHLY_CHECK_START_MONTH
    if end_month < start_month:
        end_month = start_month

    rows: list[dict[str, Any]] = []
    month_options: list[str] = []
    cursor = start_month
    while cursor <= end_month:
        label = cursor.strftime("%Y-%m")
        month_options.append(label)
        rows.append(row_map.get(label, _empty_monthly_check_row(label)))
        cursor = _next_month(cursor)

    transposed_rows: list[dict[str, Any]] = []
    for metric in MONTHLY_CHECK_METRICS:
        key = metric["key"]
        transposed_rows.append(
            {
                "key": key,
                "label": metric["label"],
                "format": metric["format"],
                "values": [row.get(key) for row in rows],
            }
        )

    return {
        "rows": rows,
        "summary": summary,
        "month_options": month_options,
        "month_options_desc": list(reversed(month_options)),
        "start_month": start_month.strftime("%Y-%m"),
        "end_month": end_month.strftime("%Y-%m"),
        "metrics": MONTHLY_CHECK_METRICS,
        "transposed_rows": transposed_rows,
    }


def build_stats(session: Session) -> dict[str, Any]:
    timeline = _build_event_timeline(session)
    base_currency = _get_base_currency(session)
    closed_sell_events = session.exec(
        select(Event)
        .where(Event.type == EventType.SELL)
        .order_by(Event.ts.asc(), Event.id.asc())
    ).all()
    closed_trade_rows = _build_closed_trade_rows(session, closed_sell_events)
    closed_trade_pnls = [
        {
            "event_id": row["event_id"],
            "ts": row["ts"],
            "ticker": row["ticker"],
            "market": row["market"],
            "currency": row["currency"],
            "realized_pnl": row["realized_pnl"],
            "cost_basis_base": row["cost_basis_base"],
            "return_pct": row["return_pct"],
        }
        for row in closed_trade_rows
    ]
    closed_trade_returns = [
        {
            "event_id": row["event_id"],
            "ts": row["ts"],
            "ticker": row["ticker"],
            "market": row["market"],
            "currency": row["currency"],
            "return_pct": row["return_pct"],
            "realized_pnl": row["realized_pnl"],
            "cost_basis_base": row["cost_basis_base"],
        }
        for row in closed_trade_rows
        if row["return_pct"] is not None and math.isfinite(float(row["return_pct"]))
    ]
    monthly_check_rows, monthly_check_summary = _build_monthly_check_rows(closed_trade_rows)
    used_currencies = {base_currency}
    for value in session.exec(select(Event.currency)).all():
        normalized = _normalize_upper_optional(value)
        if normalized:
            used_currencies.add(normalized)
    fx_chart_quote_currency = "KRW"
    fx_chart_currencies = [cur for cur in used_currencies if cur != fx_chart_quote_currency]
    fx_priority = {"USD": 0, "HKD": 1, "JPY": 2, "EUR": 3}
    fx_chart_currencies.sort(key=lambda cur: (fx_priority.get(cur, 99), cur))
    if not fx_chart_currencies:
        fx_chart_currencies = ["USD"]
    daily = _build_period_stats(timeline, "daily")
    weekly = _build_period_stats(timeline, "weekly")
    monthly = _build_period_stats(timeline, "monthly")
    yearly = _build_period_stats(timeline, "yearly")

    return {
        "base_currency": base_currency,
        "base_currency_symbol": _currency_symbol(base_currency),
        "currencies": sorted(used_currencies),
        "fx_chart_quote_currency": fx_chart_quote_currency,
        "fx_chart_currencies": fx_chart_currencies,
        "benchmark_symbols": list(BENCHMARK_SYMBOLS),
        "closed_trade_pnls": closed_trade_pnls,
        "closed_trade_returns": closed_trade_returns,
        "monthly_check_rows": monthly_check_rows,
        "monthly_check_summary": monthly_check_summary,
        "definitions": {
            "trade_count": "BUY + SELL event count",
            "win_rate_pct": "Winning SELL ratio excluding breakeven (BE) sells",
            "be_rate_pct": f"Breakeven SELL ratio; BE is reason-tagged (BE/breakeven/蹂몄젅...) or |realized_pnl| <= {WIN_RATE_BREAKEVEN_EPSILON_USD:.2f} {base_currency}",
            "mdd_pct": "Maximum drawdown (%) on period book-asset curve",
            "return_method1_pct": f"((asset_end - asset_start + withdraw_sum - deposit_sum) / asset_start) * 100; hidden when |asset_start| <= {RETURN_DENOMINATOR_MIN_BASE:.0f} {base_currency}",
            "return_method2_pct": f"((asset_end - asset_start + withdraw_sum - deposit_sum) / (asset_start + weighted_deposit_sum - weighted_withdraw_sum)) * 100; hidden when denominator <= {RETURN_DENOMINATOR_MIN_BASE:.0f} {base_currency}",
            "realized_return_pct": "Period realized return on closed trades: realized_pnl / realized_cost_basis * 100",
            "closed_trade_return_pct": "Per closed SELL: realized_pnl / allocated cost basis * 100",
            "monthly_avg_profit_pct": "Average return(%) across winning closed trades for each month",
            "monthly_avg_loss_pct": "Average loss magnitude(%) across losing closed trades for each month",
            "monthly_success_failure_ratio": "Average profit(%) / average loss(%)",
            "monthly_adjusted_success_failure_ratio": "((win_rate * avg_profit) / (loss_rate * avg_loss))",
            "monthly_hold_days": "Weighted holding days from BUY(opened_at) to SELL(ts) by sold quantity",
        },
        "current": {
            "daily": daily[0] if daily else None,
            "weekly": weekly[0] if weekly else None,
            "monthly": monthly[0] if monthly else None,
            "yearly": yearly[0] if yearly else None,
        },
        "daily": daily[:365],
        "weekly": weekly[:52],
        "monthly": monthly[:36],
        "yearly": yearly[:15],
}


def _fetch_benchmark_prices_from_yahoo_chart(symbol: str) -> tuple[list[date], list[float]]:
    period2 = int(datetime.utcnow().timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}?interval=1d&period1=0&period2={period2}&events=history&includeAdjustedClose=true"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    try:
        with urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch benchmark data for {symbol}") from exc

    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results:
        raise HTTPException(status_code=502, detail=f"No benchmark data available for {symbol}")

    result = results[0] if isinstance(results[0], dict) else {}
    timestamps = result.get("timestamp") if isinstance(result, dict) else None
    indicators = result.get("indicators") if isinstance(result, dict) else None
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote0 = quotes[0] if isinstance(quotes, list) and quotes else {}
    closes = quote0.get("close") if isinstance(quote0, dict) else None

    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise HTTPException(status_code=502, detail=f"No benchmark data available for {symbol}")

    rows: list[tuple[date, float]] = []
    for ts_value, close_value in zip(timestamps, closes):
        try:
            ts_int = int(ts_value)
            close = float(close_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close):
            continue
        rows.append((datetime.utcfromtimestamp(ts_int).date(), close))

    if not rows:
        raise HTTPException(status_code=502, detail=f"No valid close prices for {symbol}")

    rows.sort(key=lambda x: x[0])
    return [r[0] for r in rows], [r[1] for r in rows]


def _fetch_benchmark_prices_from_yfinance(symbol: str) -> tuple[list[date], list[float]]:
    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return _fetch_benchmark_prices_from_yahoo_chart(symbol)

    try:
        hist = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=False)
    except Exception:
        return _fetch_benchmark_prices_from_yahoo_chart(symbol)

    if hist is None or hist.empty or "Close" not in hist.columns:
        return _fetch_benchmark_prices_from_yahoo_chart(symbol)

    rows: list[tuple[date, float]] = []
    closes = hist["Close"].dropna()
    for idx, close_value in closes.items():
        try:
            d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
            close = float(close_value)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(close):
            continue
        rows.append((d, close))

    if not rows:
        return _fetch_benchmark_prices_from_yahoo_chart(symbol)

    rows.sort(key=lambda x: x[0])
    return [r[0] for r in rows], [r[1] for r in rows]


def _get_benchmark_prices(symbol: str) -> tuple[list[date], list[float]]:
    now = datetime.utcnow().timestamp()
    cached = _benchmark_cache.get(symbol)
    if cached and now - cached["fetched_at"] < BENCHMARK_CACHE_TTL_SECONDS:
        return cached["dates"], cached["closes"]

    dates, closes = _fetch_benchmark_prices_from_yfinance(symbol)
    _benchmark_cache[symbol] = {
        "fetched_at": now,
        "dates": dates,
        "closes": closes,
    }
    return dates, closes


def _last_close_on_or_before(dates: list[date], closes: list[float], target: date) -> float | None:
    idx = bisect_right(dates, target) - 1
    if idx < 0:
        return None
    return closes[idx]


def _calc_benchmark_period_returns(
    period_rows: list[dict[str, Any]],
    dates: list[date],
    closes: list[float],
) -> list[dict[str, Any]]:
    output = []
    for row in period_rows:
        period_start = date.fromisoformat(row["period_start"])
        period_end = date.fromisoformat(row["period_end"])
        # Use the close prior to period start as denominator so daily returns are meaningful.
        start_ref = period_start - timedelta(days=1)
        start_close = _last_close_on_or_before(dates, closes, start_ref)
        end_close = _last_close_on_or_before(dates, closes, period_end)
        if start_close is None or end_close is None or abs(start_close) < 1e-12:
            return_pct = None
        else:
            return_pct = (end_close - start_close) / start_close * 100

        output.append(
            {
                "period_key": row["period_key"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "return_pct": return_pct,
            }
        )

    # Compute cumulative benchmark return (compound) in chronological order,
    # then project back to original output order.
    factor = 1.0
    cumulative_by_key: dict[str, float | None] = {}
    for row in sorted(output, key=lambda x: x["period_start"]):
        return_pct = row["return_pct"]
        if return_pct is None:
            cumulative_by_key[row["period_key"]] = None
            continue
        factor *= 1.0 + (return_pct / 100.0)
        cumulative_by_key[row["period_key"]] = (factor - 1.0) * 100.0

    for row in output:
        row["cumulative_return_pct"] = cumulative_by_key.get(row["period_key"])
    return output


def build_benchmark_returns(session: Session, symbol: str, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    if normalized not in BENCHMARK_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"symbol must be one of {', '.join(BENCHMARK_SYMBOLS)}",
        )

    stats_payload = stats if stats is not None else build_stats(session)
    source_symbol = BENCHMARK_YF_SYMBOL_MAP.get(normalized, normalized)
    dates, closes = _get_benchmark_prices(source_symbol)
    return {
        "symbol": normalized,
        "source_symbol": source_symbol,
        "daily": _calc_benchmark_period_returns(stats_payload["daily"], dates, closes),
        "weekly": _calc_benchmark_period_returns(stats_payload["weekly"], dates, closes),
        "monthly": _calc_benchmark_period_returns(stats_payload["monthly"], dates, closes),
        "yearly": _calc_benchmark_period_returns(stats_payload["yearly"], dates, closes),
    }


def build_trade_detail(session: Session, trade_group_id: int) -> dict[str, Any]:
    group = session.get(TradeGroup, trade_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="trade_group not found")

    lots = session.exec(
        select(Lot).where(Lot.trade_group_id == trade_group_id).order_by(Lot.opened_at.asc(), Lot.id.asc())
    ).all()
    events = session.exec(
        select(Event)
        .where(Event.trade_group_id == trade_group_id)
        .order_by(Event.ts.asc(), Event.id.asc())
    ).all()

    sell_event_ids = [e.id for e in events if e.type == EventType.SELL and e.id is not None]
    alloc_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if sell_event_ids:
        allocations = session.exec(
            select(SellAllocation).where(SellAllocation.sell_event_id.in_(sell_event_ids))
        ).all()
        for alloc in allocations:
            alloc_map[alloc.sell_event_id].append(
                {"lot_id": alloc.lot_id, "qty_sold": alloc.qty_sold}
            )

    lot_rows = [
        {
            "id": lot.id,
            "ticker": lot.ticker,
            "market": lot.market,
            "exchange": lot.exchange,
            "currency": lot.currency,
            "fx_rate_to_base": lot.fx_rate_to_base,
            "opened_at": lot.opened_at,
            "qty_open": lot.qty_open,
            "entry_price": lot.entry_price,
            "sl": lot.sl,
            "tp": lot.tp,
            "buy_fee": lot.buy_fee,
            "buy_reason": lot.buy_reason,
            "note": lot.note,
            "open_risk": calc_lot_open_risk(lot),
        }
        for lot in lots
    ]

    event_rows = [
        {
            "id": event.id,
            "ts": event.ts,
            "type": event.type.value,
            "ticker": event.ticker,
            "market": event.market,
            "exchange": event.exchange,
            "currency": event.currency,
            "fx_rate_to_base": event.fx_rate_to_base,
            "qty": event.qty,
            "price": event.price,
            "fee": event.fee,
            "sl": event.sl,
            "tp": event.tp,
            "amount": event_amount(event),
            "realized_pnl": event.realized_pnl,
            "realized_pnl_local": event.realized_pnl_local,
            "reason": event.reason,
            "note": event.note,
            "image_url": event.image_url,
            "review_text": event.review_text,
            "allocations": alloc_map.get(event.id, []),
        }
        for event in events
    ]

    return {
        "trade_group": {
            "id": group.id,
            "title": group.title,
            "tags": group.tags,
            "note": group.note,
            "review": group.review,
            "opened_at": group.opened_at,
            "closed_at": group.closed_at,
        },
        "lots": lot_rows,
        "events": event_rows,
    }


def backup_database(max_backups: int = MAX_BACKUPS) -> str | None:
    if not DB_PATH.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = BACKUP_DIR / f"db_{ts}.sqlite"
    shutil.copy2(DB_PATH, backup_path)

    backups = sorted(BACKUP_DIR.glob("db_*.sqlite"))
    stale_count = len(backups) - max_backups
    if stale_count > 0:
        for old_file in backups[:stale_count]:
            old_file.unlink(missing_ok=True)

    return str(backup_path)


def save_uploaded_image(content: bytes, content_type: str | None) -> str:
    if not content:
        raise HTTPException(status_code=400, detail="empty image content")
    if len(content) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"image too large (max {MAX_IMAGE_UPLOAD_BYTES} bytes)")

    normalized_type = (content_type or "").strip().lower()
    ext = ALLOWED_IMAGE_CONTENT_TYPES.get(normalized_type)
    if ext is None:
        raise HTTPException(status_code=400, detail="unsupported image type")

    now = datetime.utcnow()
    rel_dir = Path(f"{now.year:04d}") / f"{now.month:02d}"
    target_dir = UPLOAD_DIR / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid4().hex}{ext}"
    file_path = target_dir / filename
    file_path.write_bytes(content)
    return f"/uploads/{rel_dir.as_posix()}/{filename}"


def _fetch_fx_history_from_frankfurter_range(
    from_currency: str,
    to_currency: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    url = (
        f"https://api.frankfurter.app/{start_date.isoformat()}..{end_date.isoformat()}"
        f"?from={from_currency}&to={to_currency}"
    )
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict):
        raise ValueError("invalid FX history response")

    rows: list[dict[str, Any]] = []
    for day_str in sorted(rates.keys()):
        day_rates = rates.get(day_str)
        if not isinstance(day_rates, dict):
            continue
        value = day_rates.get(to_currency)
        try:
            rate = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(rate) or rate <= 0:
            continue
        rows.append({"date": day_str, "rate": rate})
    return rows


def _fetch_fx_history_from_yahoo_chart(
    from_currency: str,
    to_currency: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    symbol = f"{from_currency}{to_currency}=X"
    period1 = int(datetime.combine(start_date, time.min).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), time.min).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}?interval=1d&period1={period1}&period2={period2}&events=history&includeAdjustedClose=true"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(req, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results:
        raise ValueError("invalid FX history response")

    result = results[0] if isinstance(results[0], dict) else {}
    timestamps = result.get("timestamp") if isinstance(result, dict) else None
    indicators = result.get("indicators") if isinstance(result, dict) else None
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote0 = quotes[0] if isinstance(quotes, list) and quotes else {}
    closes = quote0.get("close") if isinstance(quote0, dict) else None

    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise ValueError("invalid FX history response")

    rows: list[dict[str, Any]] = []
    for ts_value, close_value in zip(timestamps, closes):
        try:
            ts_int = int(ts_value)
            rate = float(close_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(rate) or rate <= 0:
            continue
        rows.append({"date": datetime.utcfromtimestamp(ts_int).date().isoformat(), "rate": rate})

    rows.sort(key=lambda x: x["date"])
    return rows


def _fetch_fx_history_by_daily_lookup(
    from_currency: str,
    to_currency: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        try:
            rate = _fetch_fx_rate_from_api(from_currency, to_currency, current)
        except Exception:
            current += timedelta(days=1)
            continue
        if math.isfinite(rate) and rate > 0:
            rows.append({"date": current.isoformat(), "rate": float(rate)})
        current += timedelta(days=1)
    return rows


def build_fx_history(
    session: Session,
    currency: str,
    days: int = 90,
    quote_currency: str | None = None,
) -> dict[str, Any]:
    base_currency = _normalize_upper_optional(quote_currency) or _get_base_currency(session)
    normalized_currency = _normalize_upper_optional(currency)
    if not normalized_currency:
        raise HTTPException(status_code=400, detail="currency is required")
    if days < 7 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 7 and 365")

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)
    if normalized_currency == base_currency:
        rows = [
            {"date": (start_date + timedelta(days=i)).isoformat(), "rate": 1.0}
            for i in range(days)
        ]
        return {
            "currency": normalized_currency,
            "base_currency": base_currency,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "rows": rows,
        }

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    providers = [
        ("frankfurter-range", _fetch_fx_history_from_frankfurter_range),
        ("yahoo-chart", _fetch_fx_history_from_yahoo_chart),
        ("daily-fallback", _fetch_fx_history_by_daily_lookup),
    ]
    for provider_name, provider in providers:
        try:
            rows = provider(normalized_currency, base_currency, start_date, end_date)
        except Exception as exc:
            errors.append(f"{provider_name}:{exc}")
            rows = []
            continue
        if rows:
            break

    if not rows:
        raise HTTPException(status_code=502, detail="failed to fetch FX history from provider")

    return {
        "currency": normalized_currency,
        "base_currency": base_currency,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rows": rows,
    }


def _write_csv(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        normalized = {}
        for field in fieldnames:
            value = row.get(field)
            if isinstance(value, datetime):
                normalized[field] = value.isoformat()
            elif isinstance(value, EventType):
                normalized[field] = value.value
            else:
                normalized[field] = value
        writer.writerow(normalized)

    return output.getvalue()


def export_events_csv(session: Session) -> str:
    rows = []
    events = session.exec(select(Event).order_by(Event.id.asc())).all()
    for event in events:
        rows.append(
            {
                "id": event.id,
                "ts": event.ts,
                "type": event.type,
                "ticker": event.ticker,
                "market": event.market,
                "exchange": event.exchange,
                "currency": event.currency,
                "fx_rate_to_base": event.fx_rate_to_base,
                "trade_group_id": event.trade_group_id,
                "lot_id": event.lot_id,
                "qty": event.qty,
                "price": event.price,
                "fee": event.fee,
                "sl": event.sl,
                "tp": event.tp,
                "cash_amount": event.cash_amount,
                "reason": event.reason,
                "note": event.note,
                "image_url": event.image_url,
                "review_text": event.review_text,
                "realized_pnl": event.realized_pnl,
                "realized_pnl_local": event.realized_pnl_local,
            }
        )

    return _write_csv(
        [
            "id",
            "ts",
            "type",
            "ticker",
            "market",
            "exchange",
            "currency",
            "fx_rate_to_base",
            "trade_group_id",
            "lot_id",
            "qty",
            "price",
            "fee",
            "sl",
            "tp",
            "cash_amount",
            "reason",
            "note",
            "image_url",
            "review_text",
            "realized_pnl",
            "realized_pnl_local",
        ],
        rows,
    )


def export_lots_csv(session: Session) -> str:
    rows = []
    lots = session.exec(select(Lot).order_by(Lot.id.asc())).all()
    for lot in lots:
        rows.append(
            {
                "id": lot.id,
                "ticker": lot.ticker,
                "market": lot.market,
                "exchange": lot.exchange,
                "currency": lot.currency,
                "fx_rate_to_base": lot.fx_rate_to_base,
                "trade_group_id": lot.trade_group_id,
                "opened_at": lot.opened_at,
                "qty_open": lot.qty_open,
                "entry_price": lot.entry_price,
                "buy_fee": lot.buy_fee,
                "sl": lot.sl,
                "tp": lot.tp,
                "buy_reason": lot.buy_reason,
                "note": lot.note,
            }
        )

    return _write_csv(
        [
            "id",
            "ticker",
            "market",
            "exchange",
            "currency",
            "fx_rate_to_base",
            "trade_group_id",
            "opened_at",
            "qty_open",
            "entry_price",
            "buy_fee",
            "sl",
            "tp",
            "buy_reason",
            "note",
        ],
        rows,
    )


def export_sell_allocations_csv(session: Session) -> str:
    rows = []
    allocations = session.exec(select(SellAllocation).order_by(SellAllocation.id.asc())).all()
    for alloc in allocations:
        rows.append(
            {
                "id": alloc.id,
                "sell_event_id": alloc.sell_event_id,
                "lot_id": alloc.lot_id,
                "qty_sold": alloc.qty_sold,
            }
        )

    return _write_csv(["id", "sell_event_id", "lot_id", "qty_sold"], rows)
