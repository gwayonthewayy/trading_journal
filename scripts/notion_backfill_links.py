#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.notion_quick_entry import (  # type: ignore[import-not-found]
    NotionClient,
    _ensure_journal,
    _find_db_id,
    _load_env_file_if_needed,
    _load_journal_schema,
    _load_position_schema,
)


def _iter_db_rows(client: NotionClient, db_id: str) -> list[dict[str, Any]]:
    cursor: str | None = None
    out: list[dict[str, Any]] = []
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = client.request("POST", f"/v1/databases/{db_id}/query", payload)
        out.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def _rich_text_to_str(prop: dict[str, Any]) -> str:
    if prop.get("type") != "rich_text":
        return ""
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


def _get_prop_by_id(props: dict[str, Any], prop_id: str) -> dict[str, Any]:
    for prop in props.values():
        if prop.get("id") == prop_id:
            return prop
    return {}


def main() -> int:
    _load_env_file_if_needed()
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing NOTION_TOKEN")

    client = NotionClient(token)
    journal_db_id = _find_db_id(client, "종목 저널 DB")
    positions_db_id = _find_db_id(client, "포지션(라운드) DB")

    journal_schema = _load_journal_schema(client, journal_db_id)
    pos_schema = _load_position_schema(client, positions_db_id)

    rows = _iter_db_rows(client, positions_db_id)
    linked = 0
    skipped = 0

    for row in rows:
        props = row.get("properties", {})
        ticker = _rich_text_to_str(_get_prop_by_id(props, pos_schema.ticker_src_id)).strip().upper()
        name = _rich_text_to_str(_get_prop_by_id(props, pos_schema.asset_name_id)).strip()
        market = _rich_text_to_str(_get_prop_by_id(props, pos_schema.market_src_id)).strip() or "미장"

        if not ticker:
            skipped += 1
            continue

        journal_id = _ensure_journal(client, journal_schema, ticker, name or ticker, market)
        if pos_schema.journal_relation_id:
            payload = {"properties": {pos_schema.journal_relation_id: {"relation": [{"id": journal_id}]}}}
            client.request("PATCH", f"/v1/pages/{row['id']}", payload)
            linked += 1
        else:
            skipped += 1

    print(f"[OK] linked positions: {linked}, skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
