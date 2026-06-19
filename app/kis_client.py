from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from app.kis_config import KisSettings


@dataclass(frozen=True)
class NormalizedExecution:
    trade_date: date
    order_no: str
    ticker: str
    symbol_name: str | None
    side: str
    market: str
    exchange: str
    currency: str
    cumulative_qty: float
    average_price: float
    executed_at: datetime
    fee: float
    tax: float
    raw_payload: dict[str, Any]


def account_fingerprint(account_no: str, product_code: str) -> str:
    return hashlib.sha256(f"{account_no}:{product_code}".encode("utf-8")).hexdigest()[:16]


def _float(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        raw = row.get(key)
        if raw not in (None, ""):
            try:
                return float(str(raw).replace(",", ""))
            except ValueError:
                continue
    return 0.0


def _text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = row.get(key)
        if raw not in (None, ""):
            return str(raw).strip()
    return ""


def _timestamp(row: dict[str, Any]) -> tuple[date, datetime]:
    date_text = _text(row, "ord_dt", "trad_dt", "trdd")
    time_text = _text(row, "ccld_tmd", "ord_tmd", "trad_tmd").zfill(6)
    trade_date = datetime.strptime(date_text, "%Y%m%d").date()
    executed_at = datetime.strptime(f"{date_text}{time_text[:6]}", "%Y%m%d%H%M%S")
    return trade_date, executed_at


def _side(row: dict[str, Any]) -> str | None:
    value = _text(row, "sll_buy_dvsn_cd", "sll_buy_dvsn_name", "sll_buy_dvsn").upper()
    if value in {"02", "BUY", "매수"} or "BUY" in value or "매수" in value:
        return "BUY"
    if value in {"01", "SELL", "매도"} or "SELL" in value or "매도" in value:
        return "SELL"
    return None


def normalize_domestic_rows(rows: Iterable[dict[str, Any]]) -> list[NormalizedExecution]:
    result: list[NormalizedExecution] = []
    for row in rows:
        qty = _float(row, "tot_ccld_qty", "ccld_qty")
        price = _float(row, "avg_prvs", "avg_prvs2", "ccld_unpr")
        side = _side(row)
        if qty <= 0 or price <= 0 or side is None:
            continue
        trade_date, executed_at = _timestamp(row)
        result.append(NormalizedExecution(
            trade_date=trade_date,
            order_no=_text(row, "odno", "odno1"),
            ticker=_text(row, "pdno", "shtn_pdno").zfill(6),
            symbol_name=_text(row, "prdt_name") or None,
            side=side,
            market="KR",
            exchange="KRX",
            currency="KRW",
            cumulative_qty=qty,
            average_price=price,
            executed_at=executed_at,
            fee=_float(row, "fee", "tot_fee"),
            tax=_float(row, "tax", "tot_tax"),
            raw_payload=dict(row),
        ))
    return result


_OVERSEAS_MARKETS = {
    "SEHK": ("HK", "HKEX", "HKD"),
    "HKS": ("HK", "HKEX", "HKD"),
    "NASD": ("US", "NASDAQ", "USD"),
    "NAS": ("US", "NASDAQ", "USD"),
    "NYSE": ("US", "NYSE", "USD"),
    "NYS": ("US", "NYSE", "USD"),
    "AMEX": ("US", "AMEX", "USD"),
    "AMS": ("US", "AMEX", "USD"),
}


def normalize_overseas_rows(rows: Iterable[dict[str, Any]]) -> list[NormalizedExecution]:
    result: list[NormalizedExecution] = []
    for row in rows:
        qty = _float(row, "ft_ccld_qty", "ccld_qty", "tot_ccld_qty")
        price = _float(row, "ft_ccld_unpr3", "ccld_unpr", "avg_prvs")
        side = _side(row)
        exchange_code = _text(row, "ovrs_excg_cd", "ovrs_excg_cd1").upper()
        market_info = _OVERSEAS_MARKETS.get(exchange_code)
        if qty <= 0 or price <= 0 or side is None or market_info is None:
            continue
        market, exchange, currency = market_info
        trade_date, executed_at = _timestamp(row)
        ticker = _text(row, "ovrs_pdno", "pdno", "shtn_pdno").upper()
        if market == "HK" and ticker.isdigit():
            ticker = str(int(ticker))
        result.append(NormalizedExecution(
            trade_date=trade_date,
            order_no=_text(row, "odno", "odno1"),
            ticker=ticker,
            symbol_name=_text(row, "ovrs_item_name", "prdt_name") or None,
            side=side,
            market=market,
            exchange=exchange,
            currency=currency,
            cumulative_qty=qty,
            average_price=price,
            executed_at=executed_at,
            fee=_float(row, "fee", "tot_fee"),
            tax=_float(row, "tax", "tot_tax"),
            raw_payload=dict(row),
        ))
    return result


class KisApiError(RuntimeError):
    pass


class KisClient:
    """Read-only KIS REST client. This class deliberately has no order methods."""

    def __init__(self, settings: KisSettings, *, timeout: int = 15) -> None:
        self.settings = settings
        self.timeout = timeout
        self._access_token = ""
        self._token_expires_at = 0.0

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        tr_id: str | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.settings.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"content-type": "application/json", "appkey": self.settings.app_key, "appsecret": self.settings.app_secret}
        if authenticated:
            headers["authorization"] = f"Bearer {self.access_token()}"
        if tr_id:
            headers["tr_id"] = tr_id
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise KisApiError(f"KIS request failed for {path}: {type(exc).__name__}") from exc
        if str(result.get("rt_cd", "0")) not in {"0", ""}:
            raise KisApiError(f"KIS API error {result.get('msg_cd', 'unknown')}: {result.get('msg1', 'request failed')}")
        return result

    def access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        result = self._request_json(
            "POST",
            "/oauth2/tokenP",
            body={"grant_type": "client_credentials", "appkey": self.settings.app_key, "appsecret": self.settings.app_secret},
            authenticated=False,
        )
        token = str(result.get("access_token", ""))
        if not token:
            raise KisApiError("KIS token response did not contain access_token")
        self._access_token = token
        self._token_expires_at = time.time() + float(result.get("expires_in", 86400))
        return token

    def approval_key(self) -> str:
        result = self._request_json(
            "POST",
            "/oauth2/Approval",
            body={"grant_type": "client_credentials", "appkey": self.settings.app_key, "secretkey": self.settings.app_secret},
            authenticated=False,
        )
        key = str(result.get("approval_key", ""))
        if not key:
            raise KisApiError("KIS approval response did not contain approval_key")
        return key

    def inquire_domestic(self, start: date, end: date) -> list[NormalizedExecution]:
        tr_id = "TTTC0081R" if self.settings.environment == "real" else "VTTC0081R"
        rows = self._paginate(
            "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id,
            {
                "CANO": self.settings.account_no,
                "ACNT_PRDT_CD": self.settings.account_product_code,
                "INQR_STRT_DT": start.strftime("%Y%m%d"),
                "INQR_END_DT": end.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            cursor_keys=("CTX_AREA_FK100", "CTX_AREA_NK100"),
        )
        return normalize_domestic_rows(rows)

    def inquire_overseas(self, start: date, end: date) -> list[NormalizedExecution]:
        tr_id = "TTTS3035R" if self.settings.environment == "real" else "VTTS3035R"
        all_rows: list[dict[str, Any]] = []
        for exchange in ("NASD", "NYSE", "AMEX", "SEHK"):
            all_rows.extend(self._paginate(
                "/uapi/overseas-stock/v1/trading/inquire-ccnl",
                tr_id,
                {
                    "CANO": self.settings.account_no,
                    "ACNT_PRDT_CD": self.settings.account_product_code,
                    "PDNO": "%",
                    "ORD_STRT_DT": start.strftime("%Y%m%d"),
                    "ORD_END_DT": end.strftime("%Y%m%d"),
                    "SLL_BUY_DVSN": "00",
                    "CCLD_NCCS_DVSN": "01",
                    "OVRS_EXCG_CD": exchange,
                    "SORT_SQN": "DS",
                    "ORD_DT": "",
                    "ORD_GNO_BRNO": "",
                    "ODNO": "",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                },
                cursor_keys=("CTX_AREA_FK200", "CTX_AREA_NK200"),
            ))
        return normalize_overseas_rows(all_rows)

    def _paginate(
        self,
        path: str,
        tr_id: str,
        params: dict[str, str],
        *,
        cursor_keys: tuple[str, str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _ in range(100):
            result = self._request_json("GET", path, params=params, tr_id=tr_id)
            output = result.get("output1", [])
            if isinstance(output, list):
                rows.extend(row for row in output if isinstance(row, dict))
            fk = str(result.get(cursor_keys[0], "") or "").strip()
            nk = str(result.get(cursor_keys[1], "") or "").strip()
            if not fk and not nk:
                break
            params[cursor_keys[0]] = fk
            params[cursor_keys[1]] = nk
        return rows
