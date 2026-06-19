from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'").strip('"')


@dataclass(frozen=True)
class KisSettings:
    environment: str
    app_key: str
    app_secret: str
    hts_id: str
    account_no: str
    account_product_code: str
    sync_enabled: bool
    write_events: bool
    order_enabled: bool
    poll_seconds: int

    @property
    def base_url(self) -> str:
        if self.environment == "real":
            return "https://openapi.koreainvestment.com:9443"
        return "https://openapivts.koreainvestment.com:29443"

    @property
    def websocket_url(self) -> str:
        if self.environment == "real":
            return "ws://ops.koreainvestment.com:21000"
        return "ws://ops.koreainvestment.com:31000"


def load_kis_settings(*, load_file: bool = True) -> KisSettings:
    if load_file:
        explicit = os.getenv("KIS_ENV_FILE", "").strip()
        path = Path(explicit).expanduser() if explicit else Path(__file__).resolve().parents[1] / ".env.kis"
        _load_env_file(path)

    environment = os.getenv("KIS_ENV", "paper").strip().lower()
    if environment not in {"paper", "real"}:
        raise RuntimeError("KIS_ENV must be paper or real")

    sync_enabled = _as_bool("KIS_SYNC_ENABLED")
    write_events = _as_bool("KIS_WRITE_EVENTS")
    order_enabled = _as_bool("KIS_ORDER_ENABLED")
    if order_enabled:
        raise RuntimeError("KIS_ORDER_ENABLED must remain false in this read-only service")
    if write_events and not sync_enabled:
        raise RuntimeError("KIS_WRITE_EVENTS requires KIS_SYNC_ENABLED=true")

    prefix = "KIS_" if environment == "real" else "KIS_PAPER_"
    app_key = os.getenv(f"{prefix}APP_KEY", "").strip()
    app_secret = os.getenv(f"{prefix}APP_SECRET", "").strip()
    account_no = os.getenv(f"{prefix}ACCOUNT_NO", "").strip()
    hts_id = os.getenv("KIS_HTS_ID", "").strip()
    product_code = os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01").strip()

    if sync_enabled:
        required = {
            f"{prefix}APP_KEY": app_key,
            f"{prefix}APP_SECRET": app_secret,
            f"{prefix}ACCOUNT_NO": account_no,
            "KIS_HTS_ID": hts_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required KIS settings: {', '.join(missing)}")
    if account_no and (len(account_no) != 8 or not account_no.isdigit()):
        raise RuntimeError(f"{prefix}ACCOUNT_NO must be the first 8 account digits")
    if len(product_code) != 2 or not product_code.isdigit():
        raise RuntimeError("KIS_ACCOUNT_PRODUCT_CODE must be two digits")

    try:
        poll_seconds = int(os.getenv("KIS_POLL_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("KIS_POLL_SECONDS must be an integer") from exc
    if poll_seconds < 15:
        raise RuntimeError("KIS_POLL_SECONDS must be at least 15")

    return KisSettings(
        environment=environment,
        app_key=app_key,
        app_secret=app_secret,
        hts_id=hts_id,
        account_no=account_no,
        account_product_code=product_code,
        sync_enabled=sync_enabled,
        write_events=write_events,
        order_enabled=False,
        poll_seconds=poll_seconds,
    )
