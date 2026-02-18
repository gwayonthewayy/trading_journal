#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@dataclass
class SourceRow:
    row_no: int
    trade_dt: datetime
    ticker: str
    name: str
    buy_qty: float
    buy_price: float
    buy_amount: float
    sell_qty: float
    sell_price: float
    sell_amount: float
    fee: float
    tax: float


def _col_to_num(col: str) -> int:
    num = 0
    for ch in col:
        num = num * 26 + (ord(ch) - 64)
    return num


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return 0.0


def _excel_serial_to_datetime(value: Any) -> datetime:
    serial = _to_float(value)
    base = datetime(1899, 12, 30)
    return base + timedelta(days=serial)


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


def _parse_source_rows(rows: list[dict[int, str]], exclude_ticker: str) -> list[SourceRow]:
    out: list[SourceRow] = []
    if not rows:
        return out

    # Skip header row at index 0.
    for idx, row in enumerate(rows[1:], start=2):
        ticker = (row.get(3) or "").strip().upper()
        if not ticker or ticker == exclude_ticker:
            continue

        buy_qty = _to_float(row.get(8))
        sell_qty = _to_float(row.get(12))
        if buy_qty <= 0 and sell_qty <= 0:
            continue

        out.append(
            SourceRow(
                row_no=idx,
                trade_dt=_excel_serial_to_datetime(row.get(1)),
                ticker=ticker,
                name=(row.get(4) or "").strip(),
                buy_qty=buy_qty,
                buy_price=_to_float(row.get(9)),
                buy_amount=_to_float(row.get(10)),
                sell_qty=sell_qty,
                sell_price=_to_float(row.get(13)),
                sell_amount=_to_float(row.get(14)),
                fee=_to_float(row.get(16)),
                tax=_to_float(row.get(17)),
            )
        )
    return out


def _split_costs(row: SourceRow) -> tuple[float, float]:
    total_cost = row.fee + row.tax
    if row.buy_qty > 0 and row.sell_qty > 0:
        buy_basis = row.buy_amount if row.buy_amount > 0 else row.buy_qty * row.buy_price
        sell_basis = row.sell_amount if row.sell_amount > 0 else row.sell_qty * row.sell_price
        total_basis = buy_basis + sell_basis
        if total_basis > 0:
            buy_cost = total_cost * (buy_basis / total_basis)
        else:
            buy_cost = total_cost * 0.5
        sell_cost = total_cost - buy_cost
        return buy_cost, sell_cost

    if row.buy_qty > 0:
        return total_cost, 0.0
    return 0.0, total_cost


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def convert(xlsx_path: Path, out_dir: Path, exclude_ticker: str) -> dict[str, Any]:
    rows = _read_sheet_rows(xlsx_path)
    source = _parse_source_rows(rows, exclude_ticker=exclude_ticker.upper())

    event_rows: list[dict[str, Any]] = []
    lot_rows: list[dict[str, Any]] = []
    alloc_rows: list[dict[str, Any]] = []

    open_lots: dict[str, deque[dict[str, float]]] = defaultdict(deque)
    open_qty_by_ticker: dict[str, float] = defaultdict(float)
    open_cost_by_ticker: dict[str, float] = defaultdict(float)

    event_id = 1
    lot_id = 1
    alloc_id = 1
    skipped_due_insufficient = 0

    for src in source:
        buy_cost, sell_cost = _split_costs(src)
        row_note = f"row={src.row_no}; source=trading history init.xlsx"

        if src.buy_qty > 0:
            event_rows.append(
                {
                    "id": event_id,
                    "ts": src.trade_dt.isoformat(),
                    "type": "BUY",
                    "ticker": src.ticker,
                    "trade_group_id": "",
                    "lot_id": lot_id,
                    "qty": src.buy_qty,
                    "price": src.buy_price,
                    "fee": buy_cost,
                    "sl": "",
                    "tp": "",
                    "cash_amount": "",
                    "reason": "import_buy",
                    "note": row_note,
                    "review_text": "",
                    "realized_pnl": "",
                }
            )
            lot_rows.append(
                {
                    "id": lot_id,
                    "ticker": src.ticker,
                    "trade_group_id": "",
                    "opened_at": src.trade_dt.isoformat(),
                    "qty_open": src.buy_qty,
                    "entry_price": src.buy_price,
                    "buy_fee": buy_cost,
                    "sl": "",
                    "tp": "",
                    "buy_reason": "import_buy",
                    "note": row_note,
                }
            )
            open_lots[src.ticker].append({"lot_id": float(lot_id), "qty": src.buy_qty})
            open_qty_by_ticker[src.ticker] += src.buy_qty
            open_cost_by_ticker[src.ticker] += src.buy_qty * src.buy_price
            event_id += 1
            lot_id += 1

        if src.sell_qty > 0:
            available_qty = open_qty_by_ticker[src.ticker]
            if src.sell_qty > available_qty + 1e-9:
                skipped_due_insufficient += 1
                continue

            avg_cost = open_cost_by_ticker[src.ticker] / available_qty if available_qty > 0 else 0.0
            realized_pnl = (src.sell_price - avg_cost) * src.sell_qty - sell_cost

            sell_event_id = event_id
            event_rows.append(
                {
                    "id": sell_event_id,
                    "ts": src.trade_dt.isoformat(),
                    "type": "SELL",
                    "ticker": src.ticker,
                    "trade_group_id": "",
                    "lot_id": "",
                    "qty": src.sell_qty,
                    "price": src.sell_price,
                    "fee": sell_cost,
                    "sl": "",
                    "tp": "",
                    "cash_amount": "",
                    "reason": "import_sell",
                    "note": row_note,
                    "review_text": "",
                    "realized_pnl": realized_pnl,
                }
            )

            remain = src.sell_qty
            while remain > 1e-9:
                head = open_lots[src.ticker][0]
                alloc_qty = min(head["qty"], remain)
                alloc_rows.append(
                    {
                        "id": alloc_id,
                        "sell_event_id": sell_event_id,
                        "lot_id": int(head["lot_id"]),
                        "qty_sold": alloc_qty,
                    }
                )
                alloc_id += 1

                head["qty"] -= alloc_qty
                remain -= alloc_qty
                if head["qty"] <= 1e-9:
                    open_lots[src.ticker].popleft()

            open_qty_by_ticker[src.ticker] -= src.sell_qty
            open_cost_by_ticker[src.ticker] -= avg_cost * src.sell_qty
            if open_qty_by_ticker[src.ticker] <= 1e-9:
                open_qty_by_ticker[src.ticker] = 0.0
                open_cost_by_ticker[src.ticker] = 0.0

            event_id += 1

    # Reflect final FIFO quantities into lots.csv qty_open.
    remaining_qty_by_lot: dict[int, float] = {}
    for lots in open_lots.values():
        for entry in lots:
            remaining_qty_by_lot[int(entry["lot_id"])] = entry["qty"]
    for lot in lot_rows:
        lid = int(lot["id"])
        lot["qty_open"] = remaining_qty_by_lot.get(lid, 0.0)

    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.csv"
    lots_path = out_dir / "lots.csv"
    alloc_path = out_dir / "sell_allocations.csv"

    _write_csv(
        events_path,
        [
            "id",
            "ts",
            "type",
            "ticker",
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
            "review_text",
            "realized_pnl",
        ],
        event_rows,
    )
    _write_csv(
        lots_path,
        [
            "id",
            "ticker",
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
        lot_rows,
    )
    _write_csv(
        alloc_path,
        ["id", "sell_event_id", "lot_id", "qty_sold"],
        alloc_rows,
    )

    return {
        "events_path": str(events_path),
        "lots_path": str(lots_path),
        "allocations_path": str(alloc_path),
        "source_rows_used": len(source),
        "events": len(event_rows),
        "lots": len(lot_rows),
        "allocations": len(alloc_rows),
        "skipped_due_insufficient_open_qty": skipped_due_insufficient,
        "excluded_ticker": exclude_ticker.upper(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert trading history init xlsx to journal-compatible CSV files."
    )
    parser.add_argument(
        "--input",
        default="/opt/trading history init.xlsx",
        help="Path to source xlsx",
    )
    parser.add_argument(
        "--out-dir",
        default="/opt",
        help="Directory to write events.csv, lots.csv, sell_allocations.csv",
    )
    parser.add_argument(
        "--exclude-ticker",
        default="TMF",
        help="Ticker to exclude from conversion",
    )
    args = parser.parse_args()

    summary = convert(
        xlsx_path=Path(args.input),
        out_dir=Path(args.out_dir),
        exclude_ticker=args.exclude_ticker,
    )
    for k, v in summary.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
