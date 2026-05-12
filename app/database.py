from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "db.sqlite"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure models are imported before metadata creation.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    ensure_compat_schema_columns()
    ensure_settings_row()


def ensure_compat_schema_columns() -> None:
    if not DB_PATH.exists():
        return

    table_columns: dict[str, dict[str, str]] = {
        "symbol": {
            "market": "TEXT",
            "exchange": "TEXT",
            "currency": "TEXT",
        },
        "lot": {
            "market": "TEXT",
            "exchange": "TEXT",
            "currency": "TEXT",
            "fx_rate_to_base": "REAL NOT NULL DEFAULT 1.0",
        },
        "event": {
            "market": "TEXT",
            "exchange": "TEXT",
            "currency": "TEXT",
            "fx_rate_to_base": "REAL NOT NULL DEFAULT 1.0",
            "realized_pnl_local": "REAL",
            "image_url": "TEXT",
        },
        "tradegroup": {
            "setup_type": "TEXT",
            "planned_entry": "REAL",
            "planned_stop": "REAL",
            "planned_risk_pct": "REAL",
            "realized_r": "REAL",
            "rule_compliance": "TEXT",
            "mistake_tag": "TEXT",
            "minervini_checklist": "TEXT",
            "candidate_id": "TEXT",
            "scan_date": "TEXT",
            "trade_status": "TEXT DEFAULT 'candidate'",
            "pivot_price": "REAL",
            "buy_zone_low": "REAL",
            "buy_zone_high": "REAL",
            "invalidation_price": "REAL",
            "overlay_snapshot_json": "TEXT",
        },
    }

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        for table_name, columns in table_columns.items():
            current_cols = {
                row[1] for row in cursor.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            }
            for col_name, col_ddl in columns.items():
                if col_name in current_cols:
                    continue
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}")
        conn.commit()


def ensure_settings_row() -> None:
    from app.models import Setting

    with Session(engine) as session:
        row = session.get(Setting, 1)
        if row is None:
            session.add(Setting(id=1))
            session.commit()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
