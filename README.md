# Trade Journal & Portfolio Web App

FastAPI + SQLite + SQLModel app for trading journal, portfolio, and stats.

## Project Spec / Handoff

- `docs/PROJECT_SPEC.md`: development handoff spec for collaborators and Codex.
- `docs/OPERATIONS_CHECKLIST.md`: pre-release security/data checklist.

## Stack

- FastAPI
- SQLite
- SQLModel
- Jinja2
- Poetry

## Install

```bash
cd /opt/trading_journal
poetry install
```

Windows (PowerShell):

```powershell
cd D:\Ï£ºÏãù\trading_journal
poetry install
```

If Poetry is not installed:

```powershell
cd D:\Ï£ºÏãù\trading_journal
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install fastapi uvicorn[standard] sqlmodel jinja2 python-multipart pandas yfinance argon2-cffi
```

## Security Environment Variables (Required)

Set all values before starting the app.

```bash
export TJ_ENV=prod
export TJ_SIGNING_SECRET="<32+ bytes random secret>"
export TJ_VIEWER_TOKEN="<long random viewer token>"
export TJ_ADMIN_TOKEN="<long random admin token>"
export TJ_ADMIN_PASSWORD_HASH="<argon2 hash>"
export TJ_AUTH_VERSION=1
export TJ_VIEWER_SESSION_HOURS=168
export TJ_ADMIN_SESSION_HOURS=12
```

Generate Argon2 hash example:

```bash
poetry run python - <<'PY'
from argon2 import PasswordHasher
print(PasswordHasher().hash("change-me"))
PY
```

Offline fallback hash (when `argon2-cffi` is unavailable):

```bash
python3 - <<'PY'
import secrets
from hashlib import pbkdf2_hmac
pwd = "change-me"
salt = secrets.token_urlsafe(16)
it = 210000
digest = pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), it).hex()
print(f"pbkdf2_sha256${it}${salt}${digest}")
PY
```

## Run (local bind only)

```bash
cd /opt/trading_journal
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows (PowerShell):

```powershell
cd D:\Ï£ºÏãù\trading_journal
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Without Poetry:

```powershell
cd D:\Ï£ºÏãù\trading_journal
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Local Runtime Convenience

- The app now auto-loads `.env.runtime` on startup.
- Lookup order: `TJ_RUNTIME_ENV_FILE` (if set) -> project root `.env.runtime` -> current working directory `.env.runtime`.
- If OS environment variables are missing, values in `.env.runtime` are used.
- Keep `.env.runtime` and `.access_info` private (already gitignored).

Notion DB bootstrap:

```powershell
$env:TJ_RUNTIME_ENV_FILE="D:\Ï£ºÏãù\notion_tradingjournal\.env.runtime"
poetry run python scripts/setup_notion_trading_os.py
```

Notion quick trade entry (auto find/create position by ticker):

```powershell
$env:TJ_RUNTIME_ENV_FILE="D:\Ï£ºÏãù\notion_tradingjournal\.env.runtime"
python scripts/notion_quick_entry.py --ticker TSLA --side Îß§Ïàò --qty 4 --price 400.47 --date 2026-02-05 --fee 0 --market ÎØ∏Ïû• --name ÌÖåÏä¨Îùº
```

## Multi-Market Fields (KR/US/HK)

- BUY/SELL accepts `market`, `exchange`, `currency`, `fx_rate_to_base`.
- `fx_rate_to_base` means: `1 unit of local currency = ? base_currency`.
- If `currency == base_currency`, fx is auto-handled as `1.0`.
- Realized PnL is calculated by allocation cost basis and stored in base currency for unified stats.

## Access URLs

- Viewer entry: `https://journal.example.com/access/view/<TJ_VIEWER_TOKEN>`
- Admin entry: `https://journal.example.com/access/admin/<TJ_ADMIN_TOKEN>`

Policy:

- Viewer: read-only (`journal`, `portfolio`, `stats`)
- Admin: read + write + CSV export

## Cloudflare Tunnel (Recommended)

1. Keep app bound to `127.0.0.1:8000`.
2. Configure `cloudflared` tunnel ingress to `http://127.0.0.1:8000`.
3. Map `journal.example.com` to the tunnel.
4. Run `cloudflared` as a systemd service.
5. Do not open inbound `8000` to the internet.

## Data / Backup

- DB: `data/db.sqlite`
- Auto backup after each successful write API call:
  - `data/backups/db_YYYYMMDD_HHMMSS_microseconds.sqlite`
- Keeps latest 200 backup files.

## Notion Quick Aliases (PowerShell)

Load aliases in current session:

```powershell
. D:\¡÷Ωƒ\trading_journal\scripts\notion_quick_entry_aliases.ps1
```

Auto-load aliases on every PowerShell startup:

```powershell
if (!(Test-Path $PROFILE)) { New-Item -Type File -Path $PROFILE -Force | Out-Null }
Add-Content $PROFILE "`n. D:\¡÷Ωƒ\trading_journal\scripts\notion_quick_entry_aliases.ps1"
```

Usage examples:

```powershell
buy TSLA 4 400.47 -Date 2026-02-05 -Fee 0 -Market πÃ¿Â -Name ≈◊ΩΩ∂Û
sell TSLA 2 412.30 -Date 2026-02-10 -Fee 0
```

## Telegram Trade Bot

Required env vars in runtime env file:

```env
TELEGRAM_BOT_TOKEN=<telegram_bot_token>
TELEGRAM_ALLOWED_CHAT_ID=<your_numeric_chat_id_optional>
```

Run bot:

```powershell
$env:TJ_RUNTIME_ENV_FILE="D:\¡÷Ωƒ\notion_tradingjournal\.env.runtime"
python D:\¡÷Ωƒ\trading_journal\scripts\telegram_trade_bot.py
```

Chat input examples:

```text
TSLA ∏≈ºˆ 4 400.47
TSLA ∏≈µµ 2 412.30 -d 2026-02-10 -f 0
/buy TSLA 4 400.47
```

Options:
- `-d` date (`YYYY-MM-DD`)
- `-f` fee
- `-m` market (e.g. πÃ¿Â)
- `-n` name (e.g. ≈◊ΩΩ∂Û)
- `--new-position` force create a new position
