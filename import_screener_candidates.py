from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlmodel import Session

from app.database import engine, init_db
from app.services import import_screener_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import VCS Minervini journal_import_candidates.json into TradeGroup candidates."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to journal_import_candidates.json")
    parser.add_argument("--apply", action="store_true", help="Write changes to the SQLite database.")
    parser.add_argument("--max-planned-risk-pct", type=float, default=8.0)
    parser.add_argument("--summary-only", action="store_true", help="Print counts without per-row details.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    init_db()
    with Session(engine) as session:
        summary = import_screener_candidates(
            session,
            payload,
            apply=args.apply,
            max_risk_pct=args.max_planned_risk_pct,
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    if args.summary_only:
        summary = {key: value for key, value in summary.items() if key != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        print("dry_run=true; rerun with --apply to write TradeGroup candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
