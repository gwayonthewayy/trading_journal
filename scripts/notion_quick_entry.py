#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, request

NOTION_VERSION = "2022-06-28"



def _env_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("TJ_RUNTIME_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root / ".env.runtime")
    candidates.append(Path.cwd() / ".env.runtime")
    return candidates



def _load_env_file_if_needed() -> None:
    if os.getenv("NOTION_TOKEN"):
        return
    env_path = next((p for p in _env_candidates() if p.exists()), None)
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"https://api.notion.com{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc

    def search_databases(self, query: str) -> list[dict[str, Any]]:
        payload = {"query": query, "filter": {"property": "object", "value": "database"}, "page_size": 100}
        out = self.request("POST", "/v1/search", payload)
        return out.get("results", [])



def _title_plain(obj: dict[str, Any]) -> str:
    return "".join(t.get("plain_text", "") for t in obj.get("title", []))



def _find_db_id(client: NotionClient, name: str) -> str:
    results = client.search_databases(name)
    for db in results:
        if _title_plain(db).strip() == name:
            return db["id"]
    for db in results:
        if name in _title_plain(db):
            return db["id"]
    raise RuntimeError(f"Cannot find database: {name}")


@dataclass
class PositionSchema:
    id: str
    title_id: str
    start_date_id: str
    status_id: str | None
    asset_name_id: str
    ticker_src_id: str
    market_src_id: str
    journal_relation_id: str | None


@dataclass
class FillSchema:
    id: str
    title_id: str
    date_id: str
    side_id: str
    qty_id: str
    price_id: str
    fee_id: str | None
    relation_to_position_id: str


@dataclass
class JournalSchema:
    id: str
    title_id: str
    ticker_id: str | None
    market_id: str | None


@dataclass
class LegacyTradeSchema:
    id: str
    title_id: str
    trade_date_id: str | None
    first_buy_date_id: str | None
    avg_buy_id: str | None
    avg_sell_id: str | None
    memo_id: str | None



def _load_position_schema(client: NotionClient, db_id: str) -> PositionSchema:
    db = client.request("GET", f"/v1/databases/{db_id}")
    props = db["properties"]
    title_id = next(v["id"] for v in props.values() if v["type"] == "title")

    if "시작일" in props:
        start_date_id = props["시작일"]["id"]
    else:
        start_date_id = next(v["id"] for v in props.values() if v["type"] == "date")

    status_id = None
    for v in props.values():
        if v["type"] == "select":
            options = [o.get("name", "") for o in v["select"].get("options", [])]
            if "OPEN" in options:
                status_id = v["id"]
                break

    for required in ["AssetName", "TickerAutoSrc", "MarketAutoSrc"]:
        if required not in props:
            raise RuntimeError(f"Property '{required}' missing in positions DB")

    journal_relation_id = None
    if "종목 저널" in props and props["종목 저널"]["type"] == "relation":
        journal_relation_id = props["종목 저널"]["id"]
    else:
        for v in props.values():
            if v["type"] == "relation":
                journal_relation_id = v["id"]
                break

    return PositionSchema(
        id=db_id,
        title_id=title_id,
        start_date_id=start_date_id,
        status_id=status_id,
        asset_name_id=props["AssetName"]["id"],
        ticker_src_id=props["TickerAutoSrc"]["id"],
        market_src_id=props["MarketAutoSrc"]["id"],
        journal_relation_id=journal_relation_id,
    )



def _load_fill_schema(client: NotionClient, db_id: str, positions_db_id: str) -> FillSchema:
    db = client.request("GET", f"/v1/databases/{db_id}")
    props = db["properties"]
    title_id = next(v["id"] for v in props.values() if v["type"] == "title")

    if "체결일시" in props:
        date_id = props["체결일시"]["id"]
    else:
        date_id = next(v["id"] for v in props.values() if v["type"] == "date")

    if "구분" in props:
        side_id = props["구분"]["id"]
    else:
        side_id = next(v["id"] for v in props.values() if v["type"] == "select")

    if "수량" in props:
        qty_id = props["수량"]["id"]
    else:
        qty_id = next(v["id"] for v in props.values() if v["type"] == "number")

    if "체결가" in props:
        price_id = props["체결가"]["id"]
    else:
        price_id = next(v["id"] for k, v in props.items() if v["type"] == "number" and v["id"] != qty_id)

    fee_id = props["수수료"]["id"] if "수수료" in props else None

    relation_id = None
    for v in props.values():
        if v["type"] == "relation" and v["relation"].get("database_id") == positions_db_id:
            relation_id = v["id"]
            break
    if relation_id is None:
        raise RuntimeError("No relation property from fills DB to positions DB")

    return FillSchema(
        id=db_id,
        title_id=title_id,
        date_id=date_id,
        side_id=side_id,
        qty_id=qty_id,
        price_id=price_id,
        fee_id=fee_id,
        relation_to_position_id=relation_id,
    )



def _load_journal_schema(client: NotionClient, db_id: str) -> JournalSchema:
    db = client.request("GET", f"/v1/databases/{db_id}")
    props = db["properties"]
    title_id = next(v["id"] for v in props.values() if v["type"] == "title")

    ticker_id = props["티커"]["id"] if "티커" in props else None
    market_id = props["시장"]["id"] if "시장" in props else None

    if ticker_id is None:
        rich = [v["id"] for v in props.values() if v["type"] == "rich_text"]
        ticker_id = rich[0] if rich else None
    if market_id is None:
        sel = [v["id"] for v in props.values() if v["type"] == "select"]
        market_id = sel[0] if sel else None

    return JournalSchema(id=db_id, title_id=title_id, ticker_id=ticker_id, market_id=market_id)



def _load_legacy_trade_schema(client: NotionClient, db_id: str) -> LegacyTradeSchema:
    db = client.request("GET", f"/v1/databases/{db_id}")
    props = db["properties"]
    title_id = next(v["id"] for v in props.values() if v["type"] == "title")

    def by_name(name: str) -> str | None:
        return props[name]["id"] if name in props else None

    return LegacyTradeSchema(
        id=db_id,
        title_id=title_id,
        trade_date_id=by_name("매매일"),
        first_buy_date_id=by_name("거래일자"),
        avg_buy_id=by_name("평균 매수가"),
        avg_sell_id=by_name("평균 매도가"),
        memo_id=by_name("Trading Memo"),
    )



def _query_journal_by_ticker(client: NotionClient, schema: JournalSchema, ticker: str) -> dict[str, Any] | None:
    if schema.ticker_id is None:
        return None
    payload = {
        "filter": {"property": schema.ticker_id, "rich_text": {"equals": ticker}},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1,
    }
    out = client.request("POST", f"/v1/databases/{schema.id}/query", payload)
    results = out.get("results", [])
    return results[0] if results else None



def _create_journal(client: NotionClient, schema: JournalSchema, ticker: str, asset_name: str, market: str) -> str:
    props: dict[str, Any] = {
        schema.title_id: {"title": [{"text": {"content": asset_name}}]},
    }
    if schema.ticker_id is not None:
        props[schema.ticker_id] = {"rich_text": [{"text": {"content": ticker}}]}
    if schema.market_id is not None:
        props[schema.market_id] = {"select": {"name": market}}
    payload = {"parent": {"database_id": schema.id}, "properties": props}
    out = client.request("POST", "/v1/pages", payload)
    return out["id"]



def _ensure_journal(client: NotionClient, schema: JournalSchema, ticker: str, asset_name: str, market: str) -> str:
    found = _query_journal_by_ticker(client, schema, ticker)
    if found:
        return found["id"]
    return _create_journal(client, schema, ticker, asset_name, market)



def _link_position_to_journal(client: NotionClient, pos_schema: PositionSchema, position_id: str, journal_id: str) -> None:
    if pos_schema.journal_relation_id is None:
        return
    payload = {"properties": {pos_schema.journal_relation_id: {"relation": [{"id": journal_id}]}}}
    client.request("PATCH", f"/v1/pages/{position_id}", payload)



def _query_position_by_ticker(client: NotionClient, schema: PositionSchema, ticker: str) -> dict[str, Any] | None:
    payload = {
        "filter": {"property": schema.ticker_src_id, "rich_text": {"equals": ticker}},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 1,
    }
    out = client.request("POST", f"/v1/databases/{schema.id}/query", payload)
    results = out.get("results", [])
    return results[0] if results else None



def _create_position(
    client: NotionClient,
    schema: PositionSchema,
    ticker: str,
    asset_name: str,
    market: str,
    trade_date: str,
    journal_id: str | None,
) -> str:
    title = f"{ticker} {trade_date[:7]}"
    props: dict[str, Any] = {
        schema.title_id: {"title": [{"text": {"content": title}}]},
        schema.start_date_id: {"date": {"start": trade_date}},
        schema.asset_name_id: {"rich_text": [{"text": {"content": asset_name}}]},
        schema.ticker_src_id: {"rich_text": [{"text": {"content": ticker}}]},
        schema.market_src_id: {"rich_text": [{"text": {"content": market}}]},
    }
    if schema.status_id:
        props[schema.status_id] = {"select": {"name": "OPEN"}}
    if journal_id and schema.journal_relation_id:
        props[schema.journal_relation_id] = {"relation": [{"id": journal_id}]}
    payload = {"parent": {"database_id": schema.id}, "properties": props}
    out = client.request("POST", "/v1/pages", payload)
    return out["id"]



def _create_fill(
    client: NotionClient,
    schema: FillSchema,
    position_id: str,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    trade_date: str,
    fee: float,
) -> str:
    title = f"{ticker} {side} {qty}@{price}"
    props: dict[str, Any] = {
        schema.title_id: {"title": [{"text": {"content": title}}]},
        schema.date_id: {"date": {"start": trade_date}},
        schema.side_id: {"select": {"name": side}},
        schema.qty_id: {"number": qty},
        schema.price_id: {"number": price},
        schema.relation_to_position_id: {"relation": [{"id": position_id}]},
    }
    if schema.fee_id is not None:
        props[schema.fee_id] = {"number": fee}
    payload = {"parent": {"database_id": schema.id}, "properties": props}
    out = client.request("POST", "/v1/pages", payload)
    return out["id"]



def _create_legacy_trade_row(
    client: NotionClient,
    schema: LegacyTradeSchema,
    ticker: str,
    asset_name: str,
    side: str,
    qty: float,
    price: float,
    trade_date: str,
    market: str,
    fee: float,
) -> str:
    title = asset_name if asset_name else ticker
    props: dict[str, Any] = {
        schema.title_id: {"title": [{"text": {"content": title}}]},
    }
    if schema.trade_date_id:
        props[schema.trade_date_id] = {"date": {"start": trade_date}}
    if schema.first_buy_date_id:
        props[schema.first_buy_date_id] = {"date": {"start": trade_date}}
    if schema.avg_buy_id and side == "매수":
        props[schema.avg_buy_id] = {"number": price}
    if schema.avg_sell_id and side == "매도":
        props[schema.avg_sell_id] = {"number": price}
    if schema.memo_id:
        memo = f"{ticker} {side} qty={qty} px={price} market={market} fee={fee}"
        props[schema.memo_id] = {"rich_text": [{"text": {"content": memo}}]}
    payload = {"parent": {"database_id": schema.id}, "properties": props}
    out = client.request("POST", "/v1/pages", payload)
    return out["id"]



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quick Notion trade entry by ticker.")
    p.add_argument("--ticker", required=True, help="Ticker, e.g. TSLA")
    p.add_argument("--side", required=True, choices=["매수", "매도"], help="매수 or 매도")
    p.add_argument("--qty", required=True, type=float, help="Quantity")
    p.add_argument("--price", required=True, type=float, help="Fill price")
    p.add_argument("--date", dest="trade_date", default=date.today().isoformat(), help="Trade date YYYY-MM-DD")
    p.add_argument("--fee", type=float, default=0.0, help="Fee")
    p.add_argument("--market", default="미장", help="Market text for new positions")
    p.add_argument("--name", default="", help="Asset display name for new positions")
    p.add_argument("--new-position", action="store_true", help="Force create a new position")
    return p.parse_args()



def main() -> int:
    _load_env_file_if_needed()
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing NOTION_TOKEN")

    args = parse_args()
    ticker = args.ticker.strip().upper()
    asset_name = args.name.strip() or ticker

    client = NotionClient(token)
    journal_db_id = _find_db_id(client, "종목 저널 DB")
    positions_db_id = _find_db_id(client, "포지션(라운드) DB")
    fills_db_id = _find_db_id(client, "체결내역 DB")

    legacy_db_id = os.getenv("NOTION_LEGACY_DB_ID", "").strip()
    if not legacy_db_id:
        try:
            legacy_db_id = _find_db_id(client, "매매일지DB")
        except RuntimeError:
            legacy_db_id = ""

    journal_schema = _load_journal_schema(client, journal_db_id)
    pos_schema = _load_position_schema(client, positions_db_id)
    fill_schema = _load_fill_schema(client, fills_db_id, positions_db_id)
    legacy_schema = _load_legacy_trade_schema(client, legacy_db_id) if legacy_db_id else None

    journal_id = _ensure_journal(client, journal_schema, ticker, asset_name, args.market)
    print(f"[OK] Journal ready: {journal_id}")

    if args.new_position:
        position_id = _create_position(
            client=client,
            schema=pos_schema,
            ticker=ticker,
            asset_name=asset_name,
            market=args.market,
            trade_date=args.trade_date,
            journal_id=journal_id,
        )
        print(f"[OK] Created new position: {position_id}")
    else:
        found = _query_position_by_ticker(client, pos_schema, ticker)
        if found:
            position_id = found["id"]
            _link_position_to_journal(client, pos_schema, position_id, journal_id)
            print(f"[OK] Reusing position: {position_id}")
        else:
            position_id = _create_position(
                client=client,
                schema=pos_schema,
                ticker=ticker,
                asset_name=asset_name,
                market=args.market,
                trade_date=args.trade_date,
                journal_id=journal_id,
            )
            print(f"[OK] Created new position: {position_id}")

    fill_id = _create_fill(
        client=client,
        schema=fill_schema,
        position_id=position_id,
        ticker=ticker,
        side=args.side,
        qty=args.qty,
        price=args.price,
        trade_date=args.trade_date,
        fee=args.fee,
    )
    print(f"[OK] Created fill: {fill_id}")

    if legacy_schema is not None:
        legacy_id = _create_legacy_trade_row(
            client=client,
            schema=legacy_schema,
            ticker=ticker,
            asset_name=asset_name,
            side=args.side,
            qty=args.qty,
            price=args.price,
            trade_date=args.trade_date,
            market=args.market,
            fee=args.fee,
        )
        print(f"[OK] Created legacy trade row: {legacy_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
