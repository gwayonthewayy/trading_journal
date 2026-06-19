from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlmodel import Session, select

from app.kis_client import KisClient, NormalizedExecution, account_fingerprint
from app.kis_config import KisSettings
from app.models import BrokerExecution, BrokerSyncState, Event, Lot
from app.schemas import BuyRequest, SellAllocationIn, SellRequest
from app.services import create_buy, create_sell, normalize_ticker


@dataclass(frozen=True)
class IngestResult:
    execution_key: str
    outcome: str
    applied_qty: float = 0
    event_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class SyncSummary:
    fetched: int
    created: int
    duplicates: int
    pending: int
    observed: int


def execution_key(account_hash: str, item: NormalizedExecution) -> str:
    identity = "|".join((
        account_hash,
        item.trade_date.isoformat(),
        item.order_no,
        item.ticker,
        item.side,
        item.market,
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _event_ids(row: BrokerExecution) -> list[int]:
    try:
        values = json.loads(row.event_ids_json or "[]")
    except json.JSONDecodeError:
        return []
    return [int(value) for value in values]


def _set_event_provenance(session: Session, event_id: int, external_id: str) -> None:
    event = session.get(Event, event_id)
    if event is None:
        raise RuntimeError(f"Journal event {event_id} disappeared during KIS sync")
    event.source_broker = "KIS"
    event.external_execution_id = external_id
    session.add(event)


def _fifo_allocations(session: Session, item: NormalizedExecution, qty: float) -> list[tuple[Lot, float]]:
    ticker = normalize_ticker(item.ticker, item.market)
    lots = session.exec(
        select(Lot)
        .where(Lot.ticker == ticker, Lot.qty_open > 0, Lot.opened_at <= item.executed_at)
        .order_by(Lot.opened_at, Lot.id)
    ).all()
    remaining = qty
    allocations: list[tuple[Lot, float]] = []
    for lot in lots:
        take = min(float(lot.qty_open), remaining)
        if take > 0:
            allocations.append((lot, take))
            remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return []
    return allocations


def _apply_buy(
    session: Session,
    row: BrokerExecution,
    item: NormalizedExecution,
    qty: float,
    price: float,
    fee: float,
) -> list[int]:
    result = create_buy(session, BuyRequest(
        ticker=item.ticker,
        market=item.market,
        exchange=item.exchange,
        currency=item.currency,
        qty=qty,
        price=price,
        fee=fee,
        symbol_name=item.symbol_name,
        ts=item.executed_at,
        note=f"KIS {row.environment} automatic execution sync",
    ))
    event_id = int(result["event_id"])
    _set_event_provenance(session, event_id, row.execution_key)
    return [event_id]


def _apply_sell(
    session: Session,
    row: BrokerExecution,
    item: NormalizedExecution,
    qty: float,
    price: float,
    fee: float,
) -> list[int] | None:
    allocations = _fifo_allocations(session, item, qty)
    if not allocations:
        return None

    grouped: dict[int | None, list[tuple[Lot, float]]] = {}
    for lot, allocated_qty in allocations:
        grouped.setdefault(lot.trade_group_id, []).append((lot, allocated_qty))

    event_ids: list[int] = []
    for group_id, group_allocations in grouped.items():
        group_qty = sum(value for _, value in group_allocations)
        group_fee = fee * (group_qty / qty) if qty else 0
        result = create_sell(session, SellRequest(
            ticker=item.ticker,
            market=item.market,
            exchange=item.exchange,
            currency=item.currency,
            price=price,
            fee=group_fee,
            ts=item.executed_at,
            trade_group_id=group_id,
            reason="KIS automatic execution sync",
            allocations=[SellAllocationIn(lot_id=int(lot.id), qty_sold=value) for lot, value in group_allocations],
        ))
        event_id = int(result["event_id"])
        _set_event_provenance(session, event_id, row.execution_key)
        event_ids.append(event_id)
    return event_ids


def ingest_execution(
    session: Session,
    account_hash: str,
    item: NormalizedExecution,
    *,
    write_events: bool,
    environment: str = "paper",
) -> IngestResult:
    key = execution_key(account_hash, item)
    row = session.get(BrokerExecution, key)
    if row is None:
        row = BrokerExecution(
            execution_key=key,
            account_hash=account_hash,
            environment=environment,
            trade_date=item.trade_date,
            order_no=item.order_no,
            ticker=item.ticker,
            symbol_name=item.symbol_name,
            side=item.side,
            market=item.market,
            exchange=item.exchange,
            currency=item.currency,
            executed_at=item.executed_at,
        )

    previous_observed_qty = row.observed_qty
    row.observed_qty = item.cumulative_qty
    row.observed_avg_price = item.average_price
    row.observed_fee = item.fee
    row.observed_tax = item.tax
    row.executed_at = item.executed_at
    row.symbol_name = item.symbol_name or row.symbol_name
    row.raw_payload_json = json.dumps(item.raw_payload, ensure_ascii=False, separators=(",", ":"), default=str)
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.flush()

    if item.cumulative_qty + 1e-9 < previous_observed_qty or item.cumulative_qty + 1e-9 < row.applied_qty:
        row.processing_status = "correction_review"
        row.last_error = "KIS cumulative fill quantity decreased; manual review required"
        session.add(row)
        return IngestResult(key, "correction_review")
    if not write_events:
        row.processing_status = "observed"
        row.last_error = None
        session.add(row)
        return IngestResult(key, "observed")

    delta_qty = item.cumulative_qty - row.applied_qty
    if delta_qty <= 1e-9:
        row.processing_status = "applied"
        row.last_error = None
        session.add(row)
        return IngestResult(key, "duplicate")

    cumulative_notional = item.cumulative_qty * item.average_price
    delta_notional = cumulative_notional - row.applied_notional
    if delta_notional <= 0:
        row.processing_status = "correction_review"
        row.last_error = "KIS cumulative notional did not increase"
        session.add(row)
        return IngestResult(key, "correction_review")
    delta_price = delta_notional / delta_qty
    delta_fee = max(0.0, (item.fee + item.tax) - (row.applied_fee + row.applied_tax))

    if item.side == "BUY":
        new_event_ids = _apply_buy(session, row, item, delta_qty, delta_price, delta_fee)
    else:
        sell_event_ids = _apply_sell(session, row, item, delta_qty, delta_price, delta_fee)
        if sell_event_ids is None:
            row.processing_status = "pending_allocation"
            row.last_error = "No sufficient open BUY lots were available"
            session.add(row)
            return IngestResult(key, "pending_allocation")
        new_event_ids = sell_event_ids

    all_event_ids = _event_ids(row) + new_event_ids
    row.event_ids_json = json.dumps(all_event_ids)
    row.applied_qty = item.cumulative_qty
    row.applied_notional = cumulative_notional
    row.applied_fee = item.fee
    row.applied_tax = item.tax
    row.processing_status = "applied"
    row.last_error = None
    session.add(row)
    session.flush()
    return IngestResult(key, "created", delta_qty, tuple(new_event_ids))


def reconcile_executions(
    session: Session,
    account_hash: str,
    executions: Iterable[NormalizedExecution],
    *,
    write_events: bool,
    environment: str,
) -> SyncSummary:
    counters = {"created": 0, "duplicate": 0, "pending_allocation": 0, "observed": 0}
    ordered = sorted(executions, key=lambda item: (item.executed_at, item.order_no, item.ticker))
    for item in ordered:
        result = ingest_execution(
            session,
            account_hash,
            item,
            write_events=write_events,
            environment=environment,
        )
        if result.outcome in counters:
            counters[result.outcome] += 1
    return SyncSummary(
        fetched=len(ordered),
        created=counters["created"],
        duplicates=counters["duplicate"],
        pending=counters["pending_allocation"],
        observed=counters["observed"],
    )


def run_rest_reconciliation(
    session: Session,
    settings: KisSettings,
    *,
    start: date | None = None,
    end: date | None = None,
    client: KisClient | None = None,
) -> SyncSummary:
    if not settings.sync_enabled:
        raise RuntimeError("KIS synchronization is disabled")
    today = date.today()
    end = end or today
    start = start or (end - timedelta(days=7))
    state = session.get(BrokerSyncState, 1) or BrokerSyncState(id=1)
    if state.paused:
        raise RuntimeError("KIS synchronization is paused")
    state.environment = settings.environment
    state.rest_status = "running"
    state.last_started_at = datetime.utcnow()
    state.last_query_start = start
    state.last_query_end = end
    state.updated_at = datetime.utcnow()
    session.add(state)
    session.flush()

    api = client or KisClient(settings)
    try:
        executions = api.inquire_domestic(start, end) + api.inquire_overseas(start, end)
        summary = reconcile_executions(
            session,
            account_fingerprint(settings.account_no, settings.account_product_code),
            executions,
            write_events=settings.write_events,
            environment=settings.environment,
        )
        state.rest_status = "ok"
        state.token_status = "ok"
        state.last_success_at = datetime.utcnow()
        state.last_error = None
        state.new_count = summary.created
        state.duplicate_count = summary.duplicates
        state.pending_count = summary.pending
        state.updated_at = datetime.utcnow()
        session.add(state)
        return summary
    except Exception as exc:
        state.rest_status = "error"
        state.last_error_at = datetime.utcnow()
        state.last_error = str(exc)[:1000]
        state.updated_at = datetime.utcnow()
        session.add(state)
        raise


def broker_sync_status(session: Session, settings: KisSettings) -> dict[str, object]:
    state = session.get(BrokerSyncState, 1) or BrokerSyncState(id=1)
    pending = session.exec(
        select(BrokerExecution)
        .where(BrokerExecution.processing_status == "pending_allocation")
        .order_by(BrokerExecution.executed_at.desc())
    ).all()
    open_lots = session.exec(select(Lot).where(Lot.qty_open > 0).order_by(Lot.opened_at, Lot.id)).all()
    return {
        "configured": bool(settings.app_key and settings.app_secret and settings.account_no),
        "sync_enabled": settings.sync_enabled,
        "write_events": settings.write_events,
        "order_enabled": False,
        "environment": settings.environment,
        "paused": state.paused,
        "rest_status": state.rest_status,
        "websocket_status": state.websocket_status,
        "token_status": state.token_status,
        "last_success_at": state.last_success_at,
        "last_error": state.last_error,
        "last_query_start": state.last_query_start,
        "last_query_end": state.last_query_end,
        "new_count": state.new_count,
        "duplicate_count": state.duplicate_count,
        "pending_count": len(pending),
        "pending": [
            {
                "execution_key": row.execution_key,
                "executed_at": row.executed_at,
                "ticker": row.ticker,
                "symbol_name": row.symbol_name,
                "market": row.market,
                "side": row.side,
                "qty": row.observed_qty - row.applied_qty,
                "price": row.observed_avg_price,
                "error": row.last_error,
                "eligible_lots": [
                    {
                        "lot_id": lot.id,
                        "qty_open": lot.qty_open,
                        "entry_price": lot.entry_price,
                        "opened_at": lot.opened_at,
                    }
                    for lot in open_lots
                    if lot.ticker == normalize_ticker(row.ticker, row.market)
                ],
            }
            for row in pending
        ],
    }


def set_sync_paused(session: Session, paused: bool) -> BrokerSyncState:
    state = session.get(BrokerSyncState, 1) or BrokerSyncState(id=1)
    state.paused = paused
    state.updated_at = datetime.utcnow()
    session.add(state)
    session.flush()
    return state


def record_sync_error(session: Session, error: Exception) -> None:
    state = session.get(BrokerSyncState, 1) or BrokerSyncState(id=1)
    state.rest_status = "error"
    state.last_error_at = datetime.utcnow()
    state.last_error = f"{type(error).__name__}: {str(error)}"[:1000]
    state.updated_at = datetime.utcnow()
    session.add(state)


def set_websocket_status(session: Session, status: str) -> None:
    state = session.get(BrokerSyncState, 1) or BrokerSyncState(id=1)
    state.websocket_status = status[:32]
    state.updated_at = datetime.utcnow()
    session.add(state)


def allocate_pending_execution(
    session: Session,
    execution_key_value: str,
    allocations: list[SellAllocationIn],
) -> IngestResult:
    row = session.get(BrokerExecution, execution_key_value)
    if row is None:
        raise ValueError("Broker execution not found")
    if row.processing_status != "pending_allocation" or row.side != "SELL":
        raise ValueError("Execution is not a pending SELL")

    delta_qty = row.observed_qty - row.applied_qty
    if abs(sum(item.qty_sold for item in allocations) - delta_qty) > 1e-9:
        raise ValueError("Allocation quantity must equal pending SELL quantity")
    lots = [session.get(Lot, item.lot_id) for item in allocations]
    if any(lot is None for lot in lots):
        raise ValueError("One or more BUY lots do not exist")
    if any(lot.ticker != normalize_ticker(row.ticker, row.market) for lot in lots if lot is not None):
        raise ValueError("Allocation includes a different ticker")

    cumulative_notional = row.observed_qty * row.observed_avg_price
    delta_notional = cumulative_notional - row.applied_notional
    if delta_qty <= 0 or delta_notional <= 0:
        raise ValueError("Pending execution has no positive unapplied quantity")
    delta_price = delta_notional / delta_qty
    grouped: dict[int | None, list[SellAllocationIn]] = {}
    lot_by_id = {int(lot.id): lot for lot in lots if lot is not None}
    for allocation in allocations:
        grouped.setdefault(lot_by_id[allocation.lot_id].trade_group_id, []).append(allocation)

    event_ids: list[int] = []
    for group_id, group_allocations in grouped.items():
        group_qty = sum(item.qty_sold for item in group_allocations)
        result = create_sell(session, SellRequest(
            ticker=row.ticker,
            market=row.market,
            exchange=row.exchange,
            currency=row.currency,
            price=delta_price,
            fee=max(0.0, (row.observed_fee + row.observed_tax) - (row.applied_fee + row.applied_tax)) * (group_qty / delta_qty),
            ts=row.executed_at,
            trade_group_id=group_id,
            reason="KIS pending execution manually allocated",
            allocations=group_allocations,
        ))
        event_id = int(result["event_id"])
        _set_event_provenance(session, event_id, row.execution_key)
        event_ids.append(event_id)

    row.event_ids_json = json.dumps(_event_ids(row) + event_ids)
    row.applied_qty = row.observed_qty
    row.applied_notional = cumulative_notional
    row.applied_fee = row.observed_fee
    row.applied_tax = row.observed_tax
    row.processing_status = "applied"
    row.last_error = None
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.flush()
    return IngestResult(row.execution_key, "created", delta_qty, tuple(event_ids))
