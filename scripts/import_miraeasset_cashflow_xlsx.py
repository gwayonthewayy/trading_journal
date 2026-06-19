#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlmodel import Session, select

from app.database import engine, init_db
from app.models import Event, EventType
from app.schemas import CashflowRequest
from app.services import _get_base_currency, create_cashflow, get_cashflow_balance
from scripts.import_miraeasset_kr_xlsx import _parse_trade_date, _read_sheet_rows, _to_float

IN_KR = "\uC785\uAE08"
OUT_KR = "\uCD9C\uAE08"
TRANSFER_IN_KR = "\uC774\uCCB4\uC785\uAE08"
TRANSFER_OUT_KR = "\uC774\uCCB4\uCD9C\uAE08"
EXTERNAL_IN_TYPES = {IN_KR, TRANSFER_IN_KR}
EXTERNAL_OUT_TYPES = {OUT_KR, TRANSFER_OUT_KR}
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


@dataclass
class PlannedCashflow:
    row_no: int
    ts: datetime
    tx_type: str
    amount_krw: float
    signed_krw: float
    fee_krw: float
    institution: str
    counterparty_name: str
    counterparty_account: str
    note: str


def _parse_cashflow_pair(
    row: dict[int, Any],
    detail: dict[int, Any],
    row_no: int,
    source_tag: str,
    reverse_sign: bool,
    apply_fee: bool,
) -> PlannedCashflow | None:
    trade_dt = _parse_trade_date(row.get(1))
    tx_type = str(row.get(2) or "").strip()
    if trade_dt is None or tx_type not in EXTERNAL_IN_TYPES | EXTERNAL_OUT_TYPES:
        return None

    is_current_statement = tx_type in {TRANSFER_IN_KR, TRANSFER_OUT_KR}
    amount_krw = _to_float(row.get(6) if is_current_statement else row.get(4))
    if amount_krw <= 0:
        return None

    hms = _parse_hms(detail.get(1))
    ts = datetime.combine(trade_dt.date(), hms or time.min)
    fee_krw = _to_float(row.get(8) if is_current_statement else detail.get(4))
    institution = str(row.get(13) if is_current_statement else row.get(3) or "").strip()
    counterparty_name = str(row.get(14) if is_current_statement else detail.get(2) or "").strip()
    counterparty_account = str(detail.get(13) if is_current_statement else detail.get(3) or "").strip()

    sign = 1.0 if tx_type in EXTERNAL_IN_TYPES else -1.0
    if reverse_sign:
        sign *= -1.0
    signed_krw = sign * amount_krw
    if apply_fee and fee_krw > 0:
        signed_krw -= fee_krw

    note = (
        f"[{source_tag}] row={row_no} "
        f"type={tx_type} institution={institution or '-'} "
        f"counterparty={counterparty_name or '-'} {counterparty_account or '-'} "
        f"amount_krw={amount_krw:.0f} fee_krw={fee_krw:.0f}"
    )
    return PlannedCashflow(
        row_no=row_no,
        ts=ts,
        tx_type=tx_type,
        amount_krw=amount_krw,
        signed_krw=signed_krw,
        fee_krw=fee_krw,
        institution=institution,
        counterparty_name=counterparty_name,
        counterparty_account=counterparty_account,
        note=note,
    )


def _parse_hms(value: Any) -> time | None:
    text = str(value or "").strip()
    if not text or not TIME_RE.match(text):
        return None
    parts = text.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) >= 3 else 0
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    return time(hh, mm, ss)


def _auto_detect_input() -> Path | None:
    roots = [Path.cwd(), PROJECT_ROOT, Path("D:/"), Path("D:/\uC8FC\uC2DD")]
    patterns = (
        "*\uC785\uCD9C\uAE08\uB0B4\uC5ED*.xlsx",
        "*\uC785\uCD9C\uAE08*.xlsx",
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


def build_plan(
    xlsx_path: Path,
    source_tag: str,
    reverse_sign: bool,
    apply_fee: bool,
) -> list[PlannedCashflow]:
    rows = _read_sheet_rows(xlsx_path)
    if len(rows) <= 2:
        return []

    plan: list[PlannedCashflow] = []
    i = 2  # skip 2 header rows
    while i < len(rows):
        row = rows[i]
        row_no = i + 1

        detail = rows[i + 1] if i + 1 < len(rows) else {}
        item = _parse_cashflow_pair(
            row,
            detail,
            row_no,
            source_tag,
            reverse_sign,
            apply_fee,
        )
        if item is not None:
            plan.append(item)

        # Current statements also use a paired detail row without a timestamp.
        if i + 1 < len(rows) and _parse_trade_date(detail.get(1)) is None:
            i += 2
        else:
            i += 1

    plan.sort(key=lambda x: (x.ts, x.row_no))
    return plan


def _existing_source_rows(session: Session, source_tag: str) -> set[int]:
    rows = session.exec(select(Event).where(Event.type == EventType.CASHFLOW)).all()
    out: set[int] = set()
    marker_prefix = f"[{source_tag}] row="
    for row in rows:
        note = row.note or ""
        idx = note.find(marker_prefix)
        if idx < 0:
            continue
        rest = note[idx + len(marker_prefix) :]
        number = []
        for ch in rest:
            if ch.isdigit():
                number.append(ch)
            else:
                break
        if number:
            out.add(int("".join(number)))
    return out


def _apply_plan(
    session: Session,
    plan: list[PlannedCashflow],
    source_tag: str,
    preserve_current_cash_balance: bool,
    skip_opening_adjustment: bool,
) -> dict[str, Any]:
    base_currency = _get_base_currency(session)
    before_cash = get_cashflow_balance(session)
    existing_rows = _existing_source_rows(session, source_tag)

    inserted = 0
    inserted_sum_base = 0.0
    skipped_existing = 0
    first_ts = None

    for item in plan:
        if item.row_no in existing_rows:
            skipped_existing += 1
            continue

        req = CashflowRequest(
            cash_amount=item.signed_krw,
            currency="KRW",
            note=item.note,
            ts=item.ts.replace(tzinfo=UTC),
        )
        result = create_cashflow(session, req)
        event = session.get(Event, result["event_id"])
        inserted += 1
        inserted_sum_base += float(event.cash_amount or 0.0)
        if first_ts is None or item.ts < first_ts:
            first_ts = item.ts

    opening_adjustment_event_id = None
    opening_adjustment_base = 0.0
    if (
        preserve_current_cash_balance
        and not skip_opening_adjustment
        and inserted > 0
        and first_ts is not None
    ):
        opening_adjustment_base = -inserted_sum_base
        if abs(opening_adjustment_base) > 1e-9:
            adj_ts = datetime.combine(first_ts.date(), time.min)
            adj_note = (
                f"[{source_tag}] opening_adjustment "
                f"preserve_pre_import_cash_balance base={base_currency}"
            )
            existing_adj = session.exec(
                select(Event).where(
                    Event.type == EventType.CASHFLOW,
                    Event.note == adj_note,
                )
            ).first()
            if existing_adj is None:
                adj_req = CashflowRequest(
                    cash_amount=opening_adjustment_base,
                    currency=base_currency,
                    note=adj_note,
                    ts=adj_ts.replace(tzinfo=UTC),
                )
                adj_res = create_cashflow(session, adj_req)
                opening_adjustment_event_id = adj_res["event_id"]
            else:
                opening_adjustment_event_id = existing_adj.id
                opening_adjustment_base = float(existing_adj.cash_amount or 0.0)

    session.commit()
    after_cash = get_cashflow_balance(session)

    return {
        "base_currency": base_currency,
        "before_cash_balance": before_cash,
        "after_cash_balance": after_cash,
        "inserted_count": inserted,
        "skipped_existing_count": skipped_existing,
        "inserted_sum_base": inserted_sum_base,
        "opening_adjustment_base": opening_adjustment_base,
        "opening_adjustment_event_id": opening_adjustment_event_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import Mirae Asset transfer history xlsx into CASHFLOW events. "
            "Default mapping: deposit=+, withdrawal=- for KRW."
        )
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to source xlsx. If omitted, script auto-detects latest file.",
    )
    parser.add_argument(
        "--source-tag",
        default="miraeasset_cashflow_20250219_20260219",
        help="Tag written in note for dedupe / traceability.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to DB. Without this flag, script prints dry-run summary only.",
    )
    parser.add_argument(
        "--reverse-sign",
        action="store_true",
        help="Reverse sign mapping (deposit=-, withdrawal=+).",
    )
    parser.add_argument(
        "--apply-fee",
        action="store_true",
        help="Apply transfer fee from detail line to net cash amount.",
    )
    parser.add_argument(
        "--skip-opening-adjustment",
        action="store_true",
        help="Do not insert opening adjustment event.",
    )
    parser.add_argument(
        "--no-preserve-current-cash-balance",
        action="store_true",
        help="Disable automatic opening adjustment that preserves current cashflow balance.",
    )
    parser.add_argument(
        "--show-limit",
        type=int,
        default=12,
        help="How many planned rows to print in dry-run summary.",
    )
    args = parser.parse_args()

    input_path: Path
    if args.input:
        input_path = Path(args.input).expanduser().resolve()
    else:
        auto = _auto_detect_input()
        if auto is None:
            print("No input file found. Pass --input explicitly.")
            raise SystemExit(1)
        input_path = auto

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        raise SystemExit(1)

    plan = build_plan(
        input_path,
        source_tag=args.source_tag,
        reverse_sign=args.reverse_sign,
        apply_fee=args.apply_fee,
    )
    if not plan:
        print("No valid transfer rows parsed.")
        raise SystemExit(0)

    in_count = sum(1 for x in plan if x.signed_krw > 0)
    out_count = sum(1 for x in plan if x.signed_krw < 0)
    net_krw = sum(x.signed_krw for x in plan)
    print(f"input_path: {input_path}")
    print(f"planned_rows: {len(plan)}")
    print(f"planned_breakdown: inflow={in_count}, outflow={out_count}")
    print(f"planned_net_krw: {net_krw:.0f}")
    print(f"date_range: {plan[0].ts.date()} ~ {plan[-1].ts.date()}")

    print("sample_rows:")
    for item in plan[: max(1, args.show_limit)]:
        print(
            f"- row={item.row_no}, ts={item.ts}, type={item.tx_type}, "
            f"signed_krw={item.signed_krw:.0f}, institution={item.institution or '-'}"
        )

    if not args.apply:
        print("dry_run_only: True")
        return

    init_db()
    with Session(engine) as session:
        result = _apply_plan(
            session=session,
            plan=plan,
            source_tag=args.source_tag,
            preserve_current_cash_balance=not args.no_preserve_current_cash_balance,
            skip_opening_adjustment=args.skip_opening_adjustment,
        )

    print("apply_done: True")
    for key in (
        "base_currency",
        "inserted_count",
        "skipped_existing_count",
        "inserted_sum_base",
        "opening_adjustment_base",
        "opening_adjustment_event_id",
        "before_cash_balance",
        "after_cash_balance",
    ):
        print(f"{key}: {result.get(key)}")


if __name__ == "__main__":
    main()

