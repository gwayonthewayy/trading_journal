#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_miraeasset_kr_xlsx import (
    SourceRow,
    apply_import_plan,
    build_import_plan,
    estimate_existing_duplicates,
    _parse_trade_date,
    _read_sheet_rows,
    _split_fee,
    _to_float,
)


def _merge_numeric_result(aggregated: dict[str, int], result: dict[str, Any]) -> None:
    for key, value in result.items():
        if key in aggregated and isinstance(value, (int, float)):
            aggregated[key] += int(value)


@dataclass
class OverseasRow:
    row_no: int
    trade_dt: Any
    currency: str
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


def _normalize_ticker(raw: str, currency: str) -> str:
    text = (raw or "").strip().upper()
    if not text:
        return ""
    if currency == "HKD":
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return digits.zfill(5)
    if currency == "JPY" and text.endswith(".T"):
        return text[:-2]
    return text


def _market_currency_from_source_currency(currency: str) -> tuple[str, str] | None:
    cur = (currency or "").strip().upper()
    if cur == "USD":
        return ("US", "USD")
    if cur == "HKD":
        return ("HK", "HKD")
    if cur == "JPY":
        return ("JP", "JPY")
    return None


def _exchange_from_market(market: str) -> str | None:
    return {"HK": "HKEX", "JP": "TSE"}.get(market)


def parse_overseas_rows(xlsx_path: Path) -> tuple[list[OverseasRow], dict[str, int]]:
    rows = _read_sheet_rows(xlsx_path)
    if not rows:
        return [], {"raw_rows": 0}

    stats = {
        "raw_rows": len(rows) - 1,
        "skipped_missing_date": 0,
        "skipped_missing_ticker": 0,
        "skipped_missing_name": 0,
        "skipped_no_qty": 0,
        "skipped_unsupported_currency": 0,
    }
    out: list[OverseasRow] = []

    # Header reference:
    # 1 매매일, 2 통화, 3 종목번호, 4 종목명,
    # 8 매수수량, 9 매수단가, 10 매수금액,
    # 12 매도수량, 13 매도단가, 14 매도금액,
    # 16 수수료, 17 세금
    for idx, row in enumerate(rows[1:], start=2):
        trade_dt = _parse_trade_date(row.get(1))
        if trade_dt is None:
            stats["skipped_missing_date"] += 1
            continue

        source_currency = (row.get(2) or "").strip().upper()
        if _market_currency_from_source_currency(source_currency) is None:
            stats["skipped_unsupported_currency"] += 1
            continue

        ticker = _normalize_ticker(str(row.get(3) or ""), source_currency)
        if not ticker:
            stats["skipped_missing_ticker"] += 1
            continue

        name = (row.get(4) or "").strip()
        if not name:
            stats["skipped_missing_name"] += 1
            continue

        buy_qty = _to_float(row.get(8))
        sell_qty = _to_float(row.get(12))
        if buy_qty <= 0 and sell_qty <= 0:
            stats["skipped_no_qty"] += 1
            continue

        out.append(
            OverseasRow(
                row_no=idx,
                trade_dt=trade_dt,
                currency=source_currency,
                ticker=ticker,
                name=name,
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
    return out, stats


def _to_source_rows(raw_rows: list[OverseasRow]) -> dict[tuple[str, str], list[SourceRow]]:
    grouped: dict[tuple[str, str], list[SourceRow]] = defaultdict(list)
    for row in raw_rows:
        mapped = _market_currency_from_source_currency(row.currency)
        if mapped is None:
            continue
        market, currency = mapped

        total_fee = max(0.0, row.fee + row.tax)
        if row.buy_qty > 0 and row.sell_qty > 0:
            # Keep split policy aligned with KR importer.
            tmp_source = SourceRow(
                row_no=row.row_no,
                trade_dt=row.trade_dt,
                name=row.name,
                buy_qty=row.buy_qty,
                buy_price=row.buy_price,
                buy_amount=row.buy_amount,
                sell_qty=row.sell_qty,
                sell_price=row.sell_price,
                sell_amount=row.sell_amount,
                fee=total_fee,
                ticker=row.ticker,
            )
            buy_fee, sell_fee = _split_fee(tmp_source)
        elif row.buy_qty > 0:
            buy_fee, sell_fee = total_fee, 0.0
        else:
            buy_fee, sell_fee = 0.0, total_fee

        grouped[(market, currency)].append(
            SourceRow(
                row_no=row.row_no,
                trade_dt=row.trade_dt,
                name=row.name,
                buy_qty=row.buy_qty,
                buy_price=row.buy_price,
                buy_amount=row.buy_amount,
                sell_qty=row.sell_qty,
                sell_price=row.sell_price,
                sell_amount=row.sell_amount,
                fee=buy_fee + sell_fee,
                ticker=row.ticker,
            )
        )
    return grouped


def _auto_detect_input() -> Path | None:
    roots = [Path.cwd(), PROJECT_ROOT, Path("D:/")]
    patterns = (
        "*\uD574\uC678\uC8FC\uC2DD*\uB9E4\uB9E4\uC77C\uC9C0*.xlsx",
        "*\uB9E4\uB9E4\uC77C\uC9C0*.xlsx",
    )
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
            "Import Mirae Asset overseas xlsx (USD/HKD). "
            "Rules: skip/trim sell-first rows based on in-file available qty."
        )
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to source xlsx. If omitted, script auto-detects latest overseas file.",
    )
    parser.add_argument(
        "--source-tag",
        default="miraeasset_overseas_20250219_20260219",
        help="Tag included in imported event notes.",
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
        help="Max number of skipped rows to print per market.",
    )
    args = parser.parse_args()

    input_path: Path
    if args.input:
        input_path = Path(args.input)
    else:
        detected = _auto_detect_input()
        if detected is None:
            raise SystemExit("No overseas xlsx found. Use --input <path>.")
        input_path = detected

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    raw_rows, parse_stats = parse_overseas_rows(input_path)
    grouped_rows = _to_source_rows(raw_rows)

    dedupe_existing = not args.no_dedupe_existing

    print(f"input_path: {input_path}")
    print(f"raw_rows: {parse_stats['raw_rows']}")
    print(f"usable_rows: {len(raw_rows)}")
    print(f"dedupe_existing: {dedupe_existing}")
    print(
        "parse_skips: "
        f"missing_date={parse_stats['skipped_missing_date']}, "
        f"missing_ticker={parse_stats['skipped_missing_ticker']}, "
        f"missing_name={parse_stats['skipped_missing_name']}, "
        f"no_qty={parse_stats['skipped_no_qty']}, "
        f"unsupported_currency={parse_stats['skipped_unsupported_currency']}"
    )

    if not grouped_rows:
        print("No rows to import after filtering.")
        return

    plans_by_market: dict[tuple[str, str], Any] = {}
    for market_key in sorted(grouped_rows.keys()):
        market, currency = market_key
        if market == "US":
            # If source has no time, default to 23:30 for US imports.
            plan = build_import_plan(
                grouped_rows[market_key],
                default_trade_time=time(23, 30, 0),
                keep_source_time_if_present=True,
            )
        else:
            plan = build_import_plan(grouped_rows[market_key])
        plans_by_market[market_key] = plan

        print(
            f"[{market}/{currency}] planned_events={len(plan.events)} "
            f"(BUY={sum(1 for x in plan.events if x.__class__.__name__ == 'PlannedBuy')}, "
            f"SELL={sum(1 for x in plan.events if x.__class__.__name__ == 'PlannedSell')})"
        )
        print(
            f"[{market}/{currency}] skipped_sell_rows={len(plan.skipped_sells)}, "
            f"unmapped_names={len(plan.unmapped_names)}"
        )
        for row in plan.skipped_sells[: args.show_limit]:
            print(
                f"- [{market}/{currency}] row={row.row_no}, date={row.trade_dt}, "
                f"name={row.name}, ticker={row.ticker}, sell_qty={row.sell_qty}, "
                f"open_before={row.available_qty}, applied_qty={row.applied_qty}, "
                f"ignored_qty={row.ignored_qty}"
            )

    if dedupe_existing:
        for market_key in sorted(plans_by_market.keys()):
            market, currency = market_key
            estimated = estimate_existing_duplicates(plans_by_market[market_key])
            print(
                f"[{market}/{currency}] "
                f"estimated_duplicate_buy_events={estimated['estimated_duplicate_buy_events']}, "
                f"estimated_duplicate_sell_events={estimated['estimated_duplicate_sell_events']}"
            )

    if not args.apply:
        print("dry_run: true (no DB writes)")
        return

    aggregated = {
        "created_buy_events": 0,
        "created_sell_events": 0,
        "skipped_existing_duplicate_buy_events": 0,
        "skipped_existing_duplicate_sell_events": 0,
        "skipped_sell_events_missing_lot_map": 0,
        "skipped_existing_buy_without_lot_map": 0,
        "skipped_sell_events_allocation_conflict": 0,
    }

    for idx, market_key in enumerate(sorted(plans_by_market.keys())):
        market, currency = market_key
        plan = plans_by_market[market_key]
        result = apply_import_plan(
            plan=plan,
            source_tag=args.source_tag,
            market=market,
            currency=currency,
            allow_nonempty_db=(args.allow_nonempty_db or idx > 0),
            dedupe_existing=dedupe_existing,
            exchange=_exchange_from_market(market),
        )
        print(f"[{market}/{currency}] apply_done")
        for key, value in result.items():
            print(f"[{market}/{currency}] {key}: {value}")
        _merge_numeric_result(aggregated, result)

    print("apply: done")
    for key, value in aggregated.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
