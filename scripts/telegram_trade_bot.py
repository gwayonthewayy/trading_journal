#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse, request


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
    if os.getenv("TELEGRAM_BOT_TOKEN"):
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


@dataclass
class TradeCommand:
    ticker: str
    side: str
    qty: float
    price: float
    trade_date: str | None
    fee: float | None
    market: str | None
    name: str | None
    new_position: bool


def _parse_trade_command(text: str) -> TradeCommand | None:
    raw = text.strip()
    if not raw:
        return None

    cmd = raw.replace(",", " ")
    cmd = re.sub(r"\s+", " ", cmd).strip()
    tokens = cmd.split(" ")
    if not tokens:
        return None

    ticker = ""
    side = ""

    if tokens[0].lower() in {"/buy", "buy", "/sell", "sell"}:
        side = "매수" if "buy" in tokens[0].lower() else "매도"
        if len(tokens) < 4:
            return None
        ticker = tokens[1].upper()
        qty_str, price_str = tokens[2], tokens[3]
        rest = tokens[4:]
    else:
        if len(tokens) < 4:
            return None
        if tokens[1] not in {"매수", "매도"}:
            return None
        ticker = tokens[0].upper()
        side = tokens[1]
        qty_str, price_str = tokens[2], tokens[3]
        rest = tokens[4:]

    try:
        qty = float(qty_str)
        price = float(price_str)
    except ValueError:
        return None

    trade_date = None
    fee = None
    market = None
    name = None
    new_position = False

    i = 0
    while i < len(rest):
        token = rest[i]
        lower = token.lower()
        if lower in {"-d", "--date"} and i + 1 < len(rest):
            trade_date = rest[i + 1]
            i += 2
            continue
        if lower in {"-f", "--fee"} and i + 1 < len(rest):
            try:
                fee = float(rest[i + 1])
            except ValueError:
                return None
            i += 2
            continue
        if lower in {"-m", "--market"} and i + 1 < len(rest):
            market = rest[i + 1]
            i += 2
            continue
        if lower in {"-n", "--name"} and i + 1 < len(rest):
            name = rest[i + 1]
            i += 2
            continue
        if lower in {"--new", "--new-position"}:
            new_position = True
            i += 1
            continue
        return None

    return TradeCommand(
        ticker=ticker,
        side=side,
        qty=qty,
        price=price,
        trade_date=trade_date,
        fee=fee,
        market=market,
        name=name,
        new_position=new_position,
    )


def _parse_trade_commands(text: str) -> list[TradeCommand]:
    commands: list[TradeCommand] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return commands
    for line in lines:
        cmd = _parse_trade_command(line)
        if cmd is None:
            raise ValueError(f"입력 형식 오류: {line}")
        commands.append(cmd)
    return commands


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        q = {"timeout": str(timeout)}
        if offset is not None:
            q["offset"] = str(offset)
        url = f"{self.base}/getUpdates?{parse.urlencode(q)}"
        with request.urlopen(url, timeout=timeout + 10) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        if not obj.get("ok"):
            return []
        return obj.get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        data = parse.urlencode({"chat_id": str(chat_id), "text": text}).encode("utf-8")
        req = request.Request(f"{self.base}/sendMessage", data=data, method="POST")
        request.urlopen(req, timeout=20).read()


def _help_text() -> str:
    return (
        "입력 예시:\n"
        "1) TSLA 매수 4 400.47\n"
        "2) TSLA 매도 2 412.30 -d 2026-02-10 -f 0\n"
        "3) /buy TSLA 4 400.47\n"
        "옵션: -d 날짜, -f 수수료, -m 시장, -n 종목명, --new-position"
    )


def _run_quick_entry(project_root: Path, cmd: TradeCommand) -> tuple[int, str]:
    script = project_root / "scripts" / "notion_quick_entry.py"
    args = [
        sys.executable,
        str(script),
        "--ticker",
        cmd.ticker,
        "--side",
        cmd.side,
        "--qty",
        str(cmd.qty),
        "--price",
        str(cmd.price),
    ]
    if cmd.trade_date:
        args.extend(["--date", cmd.trade_date])
    if cmd.fee is not None:
        args.extend(["--fee", str(cmd.fee)])
    if cmd.market:
        args.extend(["--market", cmd.market])
    if cmd.name:
        args.extend(["--name", cmd.name])
    if cmd.new_position:
        args.append("--new-position")

    proc = subprocess.run(args, cwd=str(project_root), capture_output=True, text=True)
    out = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode, out


def main() -> int:
    _load_env_file_if_needed()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    allowed_chat_id_raw = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    allowed_chat_id = int(allowed_chat_id_raw) if allowed_chat_id_raw else None

    project_root = Path(__file__).resolve().parents[1]
    tg = TelegramClient(token)
    offset: int | None = None

    print("[BOT] started")
    while True:
        try:
            updates = tg.get_updates(offset=offset, timeout=20)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                text = (msg.get("text") or "").strip()
                if not chat_id or not text:
                    continue

                if allowed_chat_id is not None and int(chat_id) != allowed_chat_id:
                    tg.send_message(chat_id, "허용되지 않은 채팅입니다.")
                    continue

                if text in {"/start", "/help"}:
                    tg.send_message(chat_id, _help_text())
                    continue
                if text in {"/id", "/chatid"}:
                    tg.send_message(chat_id, f"chat_id={chat_id}")
                    continue

                try:
                    cmds = _parse_trade_commands(text)
                except ValueError as exc:
                    tg.send_message(chat_id, f"{exc}\n\n{_help_text()}")
                    continue
                if not cmds:
                    tg.send_message(chat_id, "입력 형식이 맞지 않습니다.\n\n" + _help_text())
                    continue

                lines: list[str] = []
                for idx, cmd in enumerate(cmds, start=1):
                    code, output = _run_quick_entry(project_root, cmd)
                    if code == 0:
                        lines.append(f"{idx}. 저장 완료")
                    else:
                        lines.append(f"{idx}. 저장 실패")
                    if output:
                        tail = output.splitlines()[-1]
                        lines.append(f"   {tail}")
                tg.send_message(chat_id, "\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            print(f"[BOT] loop error: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
