#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import HTTPException
from sqlmodel import Session, select

from app.database import engine, init_db
from app.models import Event, EventType, Lot, Symbol
from app.schemas import BuyRequest, SellAllocationIn, SellRequest
from app.services import _build_lot_states_from_events, create_buy, create_sell

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@dataclass
class SourceRow:
    row_no: int
    trade_dt: datetime
    name: str
    buy_qty: float
    buy_price: float
    buy_amount: float
    sell_qty: float
    sell_price: float
    sell_amount: float
    fee: float
    ticker: str | None = None


@dataclass
class PlannedBuy:
    buy_key: str
    row_no: int
    ts: datetime
    ticker: str
    name: str
    qty: float
    price: float
    fee: float


@dataclass
class PlannedSell:
    row_no: int
    ts: datetime
    ticker: str
    name: str
    qty: float
    price: float
    fee: float
    allocations: list[tuple[str, float]]


@dataclass
class SkippedSell:
    row_no: int
    trade_dt: date
    name: str
    ticker: str
    sell_qty: float
    available_qty: float
    applied_qty: float = 0.0
    ignored_qty: float = 0.0


@dataclass
class ImportPlan:
    events: list[PlannedBuy | PlannedSell]
    skipped_sells: list[SkippedSell]
    unmapped_names: list[str]


@dataclass
class ExistingDedupIndex:
    event_counts: Counter[tuple[str, str, str, str]]
    event_counts_qp: Counter[tuple[str, str, str, float, float]]
    buy_lots_by_strict_key: dict[tuple[str, str, str], deque[int]]
    buy_lots_by_qp_key: dict[tuple[str, str, float, float], deque[int]]
    buy_lots_by_loose_key: dict[tuple[str, str], deque[int]]


def _col_to_num(col: str) -> int:
    out = 0
    for ch in col:
        out = out * 26 + (ord(ch) - 64)
    return out


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _excel_serial_to_datetime(value: Any) -> datetime | None:
    serial = _to_float(value)
    if serial <= 0:
        return None
    base = datetime(1899, 12, 30)
    return base + timedelta(days=serial)


def _parse_trade_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return _excel_serial_to_datetime(value)


def _read_shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall("m:si", NS):
        parts = [t.text or "" for t in si.findall(".//m:t", NS)]
        out.append("".join(parts))
    return out


def _get_first_sheet_path(zf: ZipFile) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall(f"{PKG_REL_NS}Relationship")
    }

    first_sheet = wb.find("m:sheets/m:sheet", NS)
    if first_sheet is None:
        raise ValueError("No sheet found in workbook")

    rid = first_sheet.attrib.get(f"{{{NS['r']}}}id")
    if not rid or rid not in rel_map:
        raise ValueError("Workbook relationship for first sheet is missing")

    target = rel_map[rid]
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    return target


def _read_sheet_rows(xlsx_path: Path) -> list[dict[int, str]]:
    with ZipFile(xlsx_path) as zf:
        sst = _read_shared_strings(zf)
        sheet_path = _get_first_sheet_path(zf)
        root = ET.fromstring(zf.read(sheet_path))

    rows = []
    for row in root.findall(".//m:sheetData/m:row", NS):
        row_dict: dict[int, str] = {}
        for cell in row.findall("m:c", NS):
            ref = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", ref)
            if not match:
                continue
            col_idx = _col_to_num(match.group(1))

            cell_type = cell.attrib.get("t")
            v = cell.find("m:v", NS)
            if v is None:
                value = ""
            else:
                raw = v.text or ""
                if cell_type == "s":
                    try:
                        value = sst[int(raw)]
                    except (IndexError, ValueError):
                        value = raw
                else:
                    value = raw

            row_dict[col_idx] = value
        if row_dict:
            rows.append(row_dict)
    return rows


def parse_source_rows(xlsx_path: Path) -> list[SourceRow]:
    rows = _read_sheet_rows(xlsx_path)
    if not rows:
        return []

    out: list[SourceRow] = []
    for idx, row in enumerate(rows[1:], start=2):
        trade_dt = _parse_trade_date(row.get(1))
        if trade_dt is None:
            continue

        name = (row.get(2) or "").strip()
        if not name:
            continue

        buy_qty = _to_float(row.get(3))
        sell_qty = _to_float(row.get(6))
        if buy_qty <= 0 and sell_qty <= 0:
            continue

        out.append(
            SourceRow(
                row_no=idx,
                trade_dt=trade_dt,
                name=name,
                buy_qty=buy_qty,
                buy_price=_to_float(row.get(4)),
                buy_amount=_to_float(row.get(5)),
                sell_qty=sell_qty,
                sell_price=_to_float(row.get(7)),
                sell_amount=_to_float(row.get(8)),
                fee=_to_float(row.get(9)),
            )
        )
    return out


def _fetch_market_page(category: str, page: int, page_size: int = 100) -> dict[str, Any]:
    url = (
        f"https://m.stock.naver.com/api/stocks/marketValue/{category}"
        f"?page={page}&pageSize={page_size}"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://m.stock.naver.com/",
        },
    )
    with urlopen(req, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected payload from Naver for {category} page {page}")
    return payload


def _build_name_to_ticker_map_from_naver() -> tuple[dict[str, str], dict[str, list[str]]]:
    by_name: dict[str, set[str]] = defaultdict(set)

    for category in ("KOSPI", "KOSDAQ"):
        first = _fetch_market_page(category, 1, 100)
        total_count = int(first.get("totalCount") or 0)
        page_size = int(first.get("pageSize") or 100)
        pages = max(1, (total_count + page_size - 1) // page_size)

        def harvest(payload: dict[str, Any]) -> None:
            for item in payload.get("stocks", []):
                if not isinstance(item, dict):
                    continue
                stock_name = str(item.get("stockName") or "").strip()
                code = str(item.get("itemCode") or "").strip()
                if not stock_name or not re.fullmatch(r"\d{6}", code):
                    continue
                by_name[stock_name].add(code)

        harvest(first)
        for page in range(2, pages + 1):
            harvest(_fetch_market_page(category, page, page_size))

    unique: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for stock_name, codes in by_name.items():
        if len(codes) == 1:
            unique[stock_name] = next(iter(codes))
        else:
            ambiguous[stock_name] = sorted(codes)
    return unique, ambiguous


def _load_name_map_from_cache(cache_path: Path) -> tuple[dict[str, str], dict[str, list[str]]] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        return None
    unique = payload.get("unique")
    ambiguous = payload.get("ambiguous")
    if not isinstance(unique, dict) or not isinstance(ambiguous, dict):
        return None

    unique_out: dict[str, str] = {}
    for name, ticker in unique.items():
        if isinstance(name, str) and isinstance(ticker, str):
            unique_out[name] = ticker

    ambiguous_out: dict[str, list[str]] = {}
    for name, codes in ambiguous.items():
        if not isinstance(name, str) or not isinstance(codes, list):
            continue
        filtered = [c for c in codes if isinstance(c, str)]
        if filtered:
            ambiguous_out[name] = filtered

    return unique_out, ambiguous_out


def _save_name_map_cache(
    cache_path: Path,
    unique: dict[str, str],
    ambiguous: dict[str, list[str]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "unique": unique,
        "ambiguous": ambiguous,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_name_map(
    cache_path: Path,
    refresh_cache: bool,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    if not refresh_cache:
        cached = _load_name_map_from_cache(cache_path)
        if cached is not None:
            return cached

    unique, ambiguous = _build_name_to_ticker_map_from_naver()
    _save_name_map_cache(cache_path, unique, ambiguous)
    return unique, ambiguous


def _split_fee(row: SourceRow) -> tuple[float, float]:
    total_fee = max(0.0, row.fee)

    if row.buy_qty > 0 and row.sell_qty > 0:
        buy_basis = row.buy_amount if row.buy_amount > 0 else row.buy_qty * row.buy_price
        sell_basis = row.sell_amount if row.sell_amount > 0 else row.sell_qty * row.sell_price
        total_basis = buy_basis + sell_basis
        if total_basis > 0:
            buy_fee = total_fee * (buy_basis / total_basis)
        else:
            buy_fee = total_fee * 0.5
        sell_fee = total_fee - buy_fee
        return buy_fee, sell_fee

    if row.buy_qty > 0:
        return total_fee, 0.0
    return 0.0, total_fee


def _normalize_name_key(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", "", name.strip()).upper()


def _name_from_event_note(note: str | None) -> str | None:
    if not note:
        return None
    match = re.search(r"(?:^|;)name=([^;]+)", note)
    if not match:
        return None
    raw = match.group(1).strip()
    return raw or None


def _event_key(
    *,
    ts: datetime,
    ticker: str,
    name: str | None,
    side: str,
) -> tuple[str, str, str, str]:
    event_date = ts.date().isoformat()
    normalized_ticker = ticker.strip().upper()
    normalized_name = _normalize_name_key(name) or normalized_ticker
    return (event_date, normalized_ticker, normalized_name, side)


def _event_qp_key(
    *,
    ts: datetime,
    ticker: str,
    side: str,
    qty: float,
    price: float,
) -> tuple[str, str, str, float, float]:
    event_date = ts.date().isoformat()
    normalized_ticker = ticker.strip().upper()
    return (
        event_date,
        normalized_ticker,
        side,
        round(float(qty), 8),
        round(float(price), 8),
    )


def _buy_qp_key(
    *,
    ts: datetime,
    ticker: str,
    qty: float,
    price: float,
) -> tuple[str, str, float, float]:
    event_date = ts.date().isoformat()
    normalized_ticker = ticker.strip().upper()
    return (
        event_date,
        normalized_ticker,
        round(float(qty), 8),
        round(float(price), 8),
    )


def _build_existing_dedup_index(session: Session) -> ExistingDedupIndex:
    symbol_rows = session.exec(select(Symbol)).all()
    symbol_name_map = {
        (row.ticker or "").strip().upper(): (row.name or "").strip()
        for row in symbol_rows
        if row.ticker
    }

    events = session.exec(
        select(Event)
        .where(
            Event.ticker.is_not(None),
            Event.type.in_([EventType.BUY, EventType.SELL]),
        )
        .order_by(Event.ts.asc(), Event.id.asc())
    ).all()

    event_counts: Counter[tuple[str, str, str, str]] = Counter()
    event_counts_qp: Counter[tuple[str, str, str, float, float]] = Counter()
    buy_lots_by_strict_key: dict[tuple[str, str, str], deque[int]] = defaultdict(deque)
    buy_lots_by_qp_key: dict[tuple[str, str, float, float], deque[int]] = defaultdict(deque)
    buy_lots_by_loose_key: dict[tuple[str, str], deque[int]] = defaultdict(deque)

    for event in events:
        ticker = (event.ticker or "").strip().upper()
        if not ticker:
            continue

        side = "BUY" if event.type == EventType.BUY else "SELL"
        event_name = _name_from_event_note(event.note) or symbol_name_map.get(ticker) or ticker
        key = _event_key(ts=event.ts, ticker=ticker, name=event_name, side=side)
        event_counts[key] += 1
        key_qp = _event_qp_key(
            ts=event.ts,
            ticker=ticker,
            side=side,
            qty=float(event.qty or 0.0),
            price=float(event.price or 0.0),
        )
        event_counts_qp[key_qp] += 1

        if side == "BUY" and event.lot_id is not None:
            strict_key = (key[0], key[1], key[2])
            buy_lots_by_strict_key[strict_key].append(int(event.lot_id))
            buy_lots_by_qp_key[
                _buy_qp_key(
                    ts=event.ts,
                    ticker=ticker,
                    qty=float(event.qty or 0.0),
                    price=float(event.price or 0.0),
                )
            ].append(int(event.lot_id))
            buy_lots_by_loose_key[(key[0], key[1])].append(int(event.lot_id))

    return ExistingDedupIndex(
        event_counts=event_counts,
        event_counts_qp=event_counts_qp,
        buy_lots_by_strict_key=buy_lots_by_strict_key,
        buy_lots_by_qp_key=buy_lots_by_qp_key,
        buy_lots_by_loose_key=buy_lots_by_loose_key,
    )


def _planned_buy_key_tuple(planned: PlannedBuy) -> tuple[str, str, str, str]:
    return _event_key(
        ts=planned.ts,
        ticker=planned.ticker,
        name=planned.name,
        side="BUY",
    )


def _planned_sell_key_tuple(planned: PlannedSell) -> tuple[str, str, str, str]:
    return _event_key(
        ts=planned.ts,
        ticker=planned.ticker,
        name=planned.name,
        side="SELL",
    )


def _planned_buy_qp_key(planned: PlannedBuy) -> tuple[str, str, str, float, float]:
    return _event_qp_key(
        ts=planned.ts,
        ticker=planned.ticker,
        side="BUY",
        qty=planned.qty,
        price=planned.price,
    )


def _planned_sell_qp_key(planned: PlannedSell) -> tuple[str, str, str, float, float]:
    return _event_qp_key(
        ts=planned.ts,
        ticker=planned.ticker,
        side="SELL",
        qty=planned.qty,
        price=planned.price,
    )


def build_import_plan(
    source_rows: list[SourceRow],
    *,
    default_trade_time: time = time(9, 0, 0),
    keep_source_time_if_present: bool = False,
) -> ImportPlan:
    open_lots: dict[str, deque[dict[str, float | str]]] = defaultdict(deque)
    events: list[PlannedBuy | PlannedSell] = []
    skipped_sells: list[SkippedSell] = []
    unmapped_names: set[str] = set()

    ordered = sorted(source_rows, key=lambda row: (row.trade_dt, row.row_no))
    for row in ordered:
        ticker = (row.ticker or "").strip()
        if not ticker:
            unmapped_names.add(row.name)
            continue

        buy_fee, sell_fee = _split_fee(row)
        base_time = default_trade_time
        if keep_source_time_if_present:
            src_time = row.trade_dt.time()
            if (
                src_time.hour != 0
                or src_time.minute != 0
                or src_time.second != 0
                or src_time.microsecond != 0
            ):
                base_time = src_time.replace(tzinfo=None)

        base_ts = datetime.combine(row.trade_dt.date(), base_time) + timedelta(seconds=row.row_no * 2)

        if row.buy_qty > 0:
            buy_key = f"row_{row.row_no}"
            events.append(
                PlannedBuy(
                    buy_key=buy_key,
                    row_no=row.row_no,
                    ts=base_ts,
                    ticker=ticker,
                    name=row.name,
                    qty=row.buy_qty,
                    price=row.buy_price,
                    fee=buy_fee,
                )
            )
            open_lots[ticker].append({"buy_key": buy_key, "qty_open": row.buy_qty})

        if row.sell_qty > 0:
            available_qty = sum(float(x["qty_open"]) for x in open_lots[ticker])
            sell_qty_to_apply = row.sell_qty
            sell_fee_to_apply = sell_fee
            # File-only FIFO is used for preview and rough shortage detection.
            # Final SELL allocation is resolved against DB runtime FIFO during apply.
            file_fifo_consumption_qty = row.sell_qty
            if row.sell_qty > available_qty + 1e-9:
                applied_qty = max(0.0, available_qty)
                ignored_qty = max(0.0, row.sell_qty - applied_qty)
                skipped_sells.append(
                    SkippedSell(
                        row_no=row.row_no,
                        trade_dt=row.trade_dt.date(),
                        name=row.name,
                        ticker=ticker,
                        sell_qty=row.sell_qty,
                        available_qty=available_qty,
                        applied_qty=applied_qty,
                        ignored_qty=ignored_qty,
                    )
                )
                # Keep full SELL event in plan and let runtime FIFO (existing DB lots)
                # decide whether it can be allocated.
                file_fifo_consumption_qty = applied_qty

            remain = file_fifo_consumption_qty
            allocations: list[tuple[str, float]] = []
            while remain > 1e-9:
                head = open_lots[ticker][0]
                head_key = str(head["buy_key"])
                head_qty = float(head["qty_open"])
                alloc_qty = min(head_qty, remain)
                allocations.append((head_key, alloc_qty))

                head["qty_open"] = head_qty - alloc_qty
                remain -= alloc_qty
                if float(head["qty_open"]) <= 1e-9:
                    open_lots[ticker].popleft()

            events.append(
                PlannedSell(
                    row_no=row.row_no,
                    ts=base_ts + timedelta(seconds=1),
                    ticker=ticker,
                    name=row.name,
                    qty=sell_qty_to_apply,
                    price=row.sell_price,
                    fee=sell_fee_to_apply,
                    allocations=allocations,
                )
            )

    return ImportPlan(
        events=events,
        skipped_sells=skipped_sells,
        unmapped_names=sorted(unmapped_names),
    )


def _build_runtime_fifo_allocations(
    session: Session,
    ticker: str,
    qty: float,
    ts: datetime,
) -> list[SellAllocationIn] | None:
    if qty <= 0:
        return []

    target = ticker.strip().upper()
    lot_states = _build_lot_states_from_events(session, up_to_ts=ts)
    open_lot_ids = [
        lot_id
        for lot_id, state in lot_states.items()
        if (state.get("ticker") or "").strip().upper() == target
        and float(state.get("qty_open") or 0.0) > 1e-9
    ]
    if not open_lot_ids:
        return None

    lots = session.exec(select(Lot).where(Lot.id.in_(open_lot_ids))).all()
    lot_by_id = {lot.id: lot for lot in lots if lot.id is not None}
    ordered_lot_ids = sorted(
        [lot_id for lot_id in open_lot_ids if lot_id in lot_by_id],
        key=lambda lid: (lot_by_id[lid].opened_at, lid),
    )

    remain = qty
    allocations: list[SellAllocationIn] = []
    for lot_id in ordered_lot_ids:
        state = lot_states.get(lot_id, {})
        available = float(state.get("qty_open") or 0.0)
        if available <= 1e-9:
            continue
        sold = min(available, remain)
        if sold <= 1e-9:
            continue
        allocations.append(SellAllocationIn(lot_id=int(lot_id), qty_sold=sold))
        remain -= sold
        if remain <= 1e-9:
            break

    if remain > 1e-9:
        return None
    return allocations


def _split_allocations_by_fx(
    session: Session,
    allocations: list[SellAllocationIn],
) -> list[list[SellAllocationIn]] | None:
    if not allocations:
        return []

    lot_ids = [alloc.lot_id for alloc in allocations]
    lots = session.exec(select(Lot).where(Lot.id.in_(lot_ids))).all()
    lot_map = {lot.id: lot for lot in lots if lot.id is not None}
    if len(lot_map) != len(set(lot_ids)):
        return None

    groups: dict[float, list[SellAllocationIn]] = {}
    order: list[float] = []
    for alloc in allocations:
        lot = lot_map.get(alloc.lot_id)
        if lot is None:
            return None
        fx_key = round(float(lot.fx_rate_to_base or 1.0), 12)
        if fx_key not in groups:
            groups[fx_key] = []
            order.append(fx_key)
        groups[fx_key].append(alloc)

    return [groups[k] for k in order]


def apply_import_plan(
    plan: ImportPlan,
    source_tag: str,
    market: str,
    currency: str,
    allow_nonempty_db: bool,
    dedupe_existing: bool,
) -> dict[str, Any]:
    init_db()

    created_buy = 0
    created_sell = 0
    buy_key_to_lot_id: dict[str, int] = {}
    skipped_existing_buy = 0
    skipped_existing_sell = 0
    skipped_sell_missing_lot_map = 0
    skipped_existing_buy_without_lot_map = 0
    skipped_sell_allocation_conflict = 0

    with Session(engine) as session:
        existing_id = session.exec(select(Event.id).limit(1)).first()
        has_existing = existing_id is not None
        if not allow_nonempty_db and has_existing:
            raise RuntimeError(
                "database already has events. Use --allow-nonempty-db if you really want to append."
            )

        dedup_counts: Counter[tuple[str, str, str, str]] = Counter()
        dedup_counts_qp: Counter[tuple[str, str, str, float, float]] = Counter()
        dedup_buy_strict: dict[tuple[str, str, str], deque[int]] = defaultdict(deque)
        dedup_buy_qp: dict[tuple[str, str, float, float], deque[int]] = defaultdict(deque)
        dedup_buy_loose: dict[tuple[str, str], deque[int]] = defaultdict(deque)
        if dedupe_existing and has_existing:
            idx = _build_existing_dedup_index(session)
            dedup_counts = idx.event_counts
            dedup_counts_qp = idx.event_counts_qp
            dedup_buy_strict = idx.buy_lots_by_strict_key
            dedup_buy_qp = idx.buy_lots_by_qp_key
            dedup_buy_loose = idx.buy_lots_by_loose_key

        try:
            for planned in plan.events:
                if isinstance(planned, PlannedBuy):
                    if dedupe_existing:
                        key = _planned_buy_key_tuple(planned)
                        key_qp = _planned_buy_qp_key(planned)

                        duplicated = False
                        if dedup_counts[key] > 0:
                            dedup_counts[key] -= 1
                            if dedup_counts_qp[key_qp] > 0:
                                dedup_counts_qp[key_qp] -= 1
                            duplicated = True
                        elif dedup_counts_qp[key_qp] > 0:
                            dedup_counts_qp[key_qp] -= 1
                            if dedup_counts[key] > 0:
                                dedup_counts[key] -= 1
                            duplicated = True

                        if duplicated:
                            skipped_existing_buy += 1

                            strict_lookup = (key[0], key[1], key[2])
                            qp_lookup = (key_qp[0], key_qp[1], key_qp[3], key_qp[4])
                            lot_id: int | None = None
                            if dedup_buy_strict[strict_lookup]:
                                lot_id = dedup_buy_strict[strict_lookup].popleft()
                            elif dedup_buy_qp[qp_lookup]:
                                lot_id = dedup_buy_qp[qp_lookup].popleft()
                            else:
                                loose_lookup = (key[0], key[1])
                                if dedup_buy_loose[loose_lookup]:
                                    lot_id = dedup_buy_loose[loose_lookup].popleft()

                            if lot_id is not None:
                                buy_key_to_lot_id[planned.buy_key] = lot_id
                            else:
                                skipped_existing_buy_without_lot_map += 1
                            continue

                    note = (
                        f"import={source_tag};row={planned.row_no};side=BUY;"
                        f"name={planned.name}"
                    )
                    req = BuyRequest(
                        ticker=planned.ticker,
                        market=market,
                        currency=currency,
                        qty=planned.qty,
                        price=planned.price,
                        fee=planned.fee,
                        buy_reason="import_buy",
                        note=note,
                        symbol_name=planned.name,
                        ts=planned.ts,
                    )
                    out = create_buy(session, req)
                    lot_id = out.get("lot_id")
                    if lot_id is None:
                        raise RuntimeError(f"missing lot_id for buy row {planned.row_no}")
                    buy_key_to_lot_id[planned.buy_key] = int(lot_id)
                    created_buy += 1
                    continue

                if dedupe_existing:
                    key = _planned_sell_key_tuple(planned)
                    key_qp = _planned_sell_qp_key(planned)
                    duplicated = False
                    if dedup_counts[key] > 0:
                        dedup_counts[key] -= 1
                        if dedup_counts_qp[key_qp] > 0:
                            dedup_counts_qp[key_qp] -= 1
                        duplicated = True
                    elif dedup_counts_qp[key_qp] > 0:
                        dedup_counts_qp[key_qp] -= 1
                        if dedup_counts[key] > 0:
                            dedup_counts[key] -= 1
                        duplicated = True
                    if duplicated:
                        skipped_existing_sell += 1
                        continue

                allocations_in = _build_runtime_fifo_allocations(
                    session=session,
                    ticker=planned.ticker,
                    qty=planned.qty,
                    ts=planned.ts,
                )
                if not allocations_in:
                    skipped_sell_missing_lot_map += 1
                    continue

                note = (
                    f"import={source_tag};row={planned.row_no};side=SELL;"
                    f"name={planned.name}"
                )
                fx_groups = _split_allocations_by_fx(session, allocations_in)
                if fx_groups is None or not fx_groups:
                    skipped_sell_allocation_conflict += 1
                    continue

                group_qtys = [sum(float(x.qty_sold) for x in group) for group in fx_groups]
                total_qty = sum(group_qtys)
                if total_qty <= 0:
                    skipped_sell_allocation_conflict += 1
                    continue

                fee_remaining = planned.fee
                group_reqs: list[SellRequest] = []
                for idx, group in enumerate(fx_groups):
                    if idx == len(fx_groups) - 1:
                        fee_for_group = fee_remaining
                    else:
                        ratio = group_qtys[idx] / total_qty
                        fee_for_group = planned.fee * ratio
                        fee_remaining -= fee_for_group
                    group_note = (
                        note
                        if len(fx_groups) == 1
                        else f"{note};fx_split={idx + 1}/{len(fx_groups)}"
                    )
                    group_reqs.append(
                        SellRequest(
                            ticker=planned.ticker,
                            market=market,
                            currency=currency,
                            price=planned.price,
                            fee=fee_for_group,
                            reason="import_sell",
                            note=group_note,
                            ts=planned.ts,
                            allocations=group,
                        )
                    )

                sell_failed = False
                for req in group_reqs:
                    try:
                        create_sell(session, req)
                        created_sell += 1
                    except HTTPException as exc:
                        detail = str(getattr(exc, "detail", "") or "")
                        if exc.status_code == 400 and (
                            "allocation exceeds open qty" in detail
                            or "allocation sum exceeds open qty" in detail
                            or "allocation includes different ticker lot" in detail
                            or "one or more lots do not exist" in detail
                            or "missing historical lot state" in detail
                            or "allocation lots must have same fx_rate_to_base" in detail
                        ):
                            skipped_sell_allocation_conflict += 1
                            sell_failed = True
                            break
                        raise
                if sell_failed:
                    continue

            session.commit()
        except Exception:
            session.rollback()
            raise

    return {
        "created_buy_events": created_buy,
        "created_sell_events": created_sell,
        "skipped_existing_duplicate_buy_events": skipped_existing_buy,
        "skipped_existing_duplicate_sell_events": skipped_existing_sell,
        "skipped_sell_events_missing_lot_map": skipped_sell_missing_lot_map,
        "skipped_existing_buy_without_lot_map": skipped_existing_buy_without_lot_map,
        "skipped_sell_events_allocation_conflict": skipped_sell_allocation_conflict,
    }


def estimate_existing_duplicates(plan: ImportPlan) -> dict[str, int]:
    init_db()
    with Session(engine) as session:
        idx = _build_existing_dedup_index(session)
    counts = Counter(idx.event_counts)
    counts_qp = Counter(idx.event_counts_qp)

    dup_buy = 0
    dup_sell = 0
    for planned in plan.events:
        if isinstance(planned, PlannedBuy):
            key = _planned_buy_key_tuple(planned)
            key_qp = _planned_buy_qp_key(planned)
            if counts[key] > 0:
                counts[key] -= 1
                if counts_qp[key_qp] > 0:
                    counts_qp[key_qp] -= 1
                dup_buy += 1
            elif counts_qp[key_qp] > 0:
                counts_qp[key_qp] -= 1
                if counts[key] > 0:
                    counts[key] -= 1
                dup_buy += 1
            continue

        key = _planned_sell_key_tuple(planned)
        key_qp = _planned_sell_qp_key(planned)
        if counts[key] > 0:
            counts[key] -= 1
            if counts_qp[key_qp] > 0:
                counts_qp[key_qp] -= 1
            dup_sell += 1
        elif counts_qp[key_qp] > 0:
            counts_qp[key_qp] -= 1
            if counts[key] > 0:
                counts[key] -= 1
            dup_sell += 1

    return {
        "estimated_duplicate_buy_events": dup_buy,
        "estimated_duplicate_sell_events": dup_sell,
    }


def _auto_detect_input() -> Path | None:
    roots = [Path.cwd(), PROJECT_ROOT, Path("D:/")]
    patterns = ("*국장*매매일지*.xlsx", "*매매일지*.xlsx")
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            try:
                candidates.extend(root.glob(pattern))
            except OSError:
                continue
    if not candidates:
        return None
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import Mirae Asset KR trade history xlsx into trading journal DB. "
            "Rows with insufficient in-file open qty are still planned and "
            "then resolved against DB runtime FIFO during apply."
        )
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to source xlsx. If omitted, script auto-detects the latest matching file.",
    )
    parser.add_argument(
        "--source-tag",
        default="miraeasset_kr_20250101_20260219",
        help="Tag included in imported event notes.",
    )
    parser.add_argument(
        "--market",
        default="KR",
        help="Market to store for imported events (default: KR).",
    )
    parser.add_argument(
        "--currency",
        default="KRW",
        help="Currency to store for imported events (default: KRW).",
    )
    parser.add_argument(
        "--name-map-cache",
        default="data/cache/naver_kr_name_map.json",
        help="Path to cache file for Naver KR name->ticker map.",
    )
    parser.add_argument(
        "--refresh-name-map",
        action="store_true",
        help="Ignore cache and rebuild Naver KR name->ticker map from API.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to DB. Without this flag, script runs as dry-run.",
    )
    parser.add_argument(
        "--allow-nonempty-db",
        action="store_true",
        help="Allow import even when DB already has events.",
    )
    parser.add_argument(
        "--no-dedupe-existing",
        action="store_true",
        help="Disable dedupe against existing DB events (default: dedupe enabled).",
    )
    parser.add_argument(
        "--show-limit",
        type=int,
        default=20,
        help="Max number of names/rows to print in preview lists.",
    )
    args = parser.parse_args()

    input_path: Path
    if args.input:
        input_path = Path(args.input)
    else:
        detected = _auto_detect_input()
        if detected is None:
            raise SystemExit("No input xlsx found. Use --input <path>.")
        input_path = detected

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    source_rows = parse_source_rows(input_path)
    if not source_rows:
        raise SystemExit("No usable trade rows found in source file.")

    cache_path = Path(args.name_map_cache)
    unique_map, ambiguous_map = load_name_map(cache_path, args.refresh_name_map)
    for row in source_rows:
        row.ticker = unique_map.get(row.name)

    plan = build_import_plan(source_rows)
    dedupe_existing = not args.no_dedupe_existing

    print(f"input_path: {input_path}")
    print(f"source_rows: {len(source_rows)}")
    print(f"name_map_unique: {len(unique_map)}")
    print(f"name_map_ambiguous: {len(ambiguous_map)}")
    print(f"dedupe_existing: {dedupe_existing}")
    print(f"planned_events: {len(plan.events)}")
    print(
        "planned_breakdown:"
        f" BUY={sum(1 for x in plan.events if isinstance(x, PlannedBuy))}"
        f", SELL={sum(1 for x in plan.events if isinstance(x, PlannedSell))}"
    )
    print(f"file_fifo_shortfall_rows: {len(plan.skipped_sells)}")
    print(f"skipped_sell_rows: {len(plan.skipped_sells)}")
    print(f"unmapped_names: {len(plan.unmapped_names)}")

    if plan.unmapped_names:
        print("unmapped_name_samples:")
        for name in plan.unmapped_names[: args.show_limit]:
            print(f"- {name}")

    if plan.skipped_sells:
        print("file_fifo_shortfall_samples:")
        for row in plan.skipped_sells[: args.show_limit]:
            print(
                f"- row={row.row_no}, date={row.trade_dt}, name={row.name}, "
                f"ticker={row.ticker}, sell_qty={row.sell_qty}, open_before={row.available_qty}, "
                f"applied_qty={row.applied_qty}, ignored_qty={row.ignored_qty}"
            )

    if dedupe_existing:
        estimated = estimate_existing_duplicates(plan)
        for key, value in estimated.items():
            print(f"{key}: {value}")

    if not args.apply:
        print("dry_run: true (no DB writes)")
        return

    if plan.unmapped_names:
        raise SystemExit(
            "Cannot apply import because unmapped names exist. "
            "Fix mapping first or rerun when map is updated."
        )

    result = apply_import_plan(
        plan=plan,
        source_tag=args.source_tag,
        market=str(args.market).strip().upper(),
        currency=str(args.currency).strip().upper(),
        allow_nonempty_db=args.allow_nonempty_db,
        dedupe_existing=dedupe_existing,
    )
    print("apply: done")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
