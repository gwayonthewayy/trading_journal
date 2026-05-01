# Trading Journal Handoff

This file is the working handoff for Codex, Google Antigravity, and any other machine that continues this project.

## Project

- App: personal trading journal, portfolio, and stats web app
- Stack: Python 3.12, FastAPI, SQLModel, SQLite, Jinja2
- Main local repo: `D:\주식\trading_journal`
- Friend server repo: `/opt/gyu/trading_journal`
- GitHub remote: `https://github.com/gwayonthewayy/trading_journal.git`
- Runtime DB: `data/db.sqlite`
- Runtime uploads: `data/uploads`
- Runtime env: `.env.runtime`

## Mandatory Git Rule

Always make a backup commit before and after meaningful work.

Before changing anything:

```bash
git status
git add -A
git commit -m "backup: before <short task name>"
git push
```

After the task is done and checked:

```bash
git status
git add -A
git commit -m "feat: <short task result>"
git push
```

If there are no changes before starting, note that `git status` is clean and continue. Do not force push. Do not reset hard unless the user explicitly asks.

## Sensitive Data Rule

Do not commit runtime/private files.

These should stay local or be transferred privately:

- `.env.runtime`
- `.access_info`
- `data/db.sqlite`
- `data/uploads/`
- `data/backups/`
- `runtime_bundle*.zip`
- `trading_data.zip`

Check before every commit:

```bash
git status --short
git diff --cached --name-only
```

If any sensitive file is staged, unstage it:

```bash
git restore --staged <file>
```

## Local Development

Windows PowerShell:

```powershell
cd "D:\주식\trading_journal"
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Admin access uses:

```text
http://127.0.0.1:8000/access/admin/<TJ_ADMIN_TOKEN>
```

Read `<TJ_ADMIN_TOKEN>` from `.env.runtime`. Do not paste the real token into committed docs.

## Friend Server

Main path:

```bash
cd /opt/gyu/trading_journal
```

The intended production service should point to this path, not the older `/opt/trading_journal` path.

Expected systemd service settings:

```ini
WorkingDirectory=/opt/gyu/trading_journal
EnvironmentFile=/opt/gyu/trading_journal/.env.runtime
ExecStart=/home/gyu123/.local/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

After service edits, the server admin should run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart trading-journal
sudo systemctl status trading-journal --no-pager -l
```

Check local service:

```bash
ss -ltnp | grep :8000
curl -s http://127.0.0.1:8000/access | head
```

Cloudflare Tunnel is expected to route to `http://127.0.0.1:8000`.

## Data Transfer

Code goes through GitHub.

Runtime data does not go through GitHub. Transfer it privately:

- `.env.runtime`
- `data/db.sqlite`
- `data/uploads/`

On Windows, if needed, create a private runtime bundle outside Git:

```powershell
cd "D:\주식\trading_journal"
Compress-Archive -Path ".env.runtime","data\db.sqlite","data\uploads" -DestinationPath "D:\workspace\runtime_bundle_latest.zip" -Force
```

Upload privately to the server and restore into `/opt/gyu/trading_journal`.

## Current App Areas

- `app/main.py`: FastAPI routes, pages, API endpoints
- `app/services.py`: trading logic, portfolio/stats calculations, market data helpers
- `app/models.py`: SQLModel tables
- `app/schemas.py`: request/response schemas
- `app/templates/`: Jinja pages
- `app/static/style.css`: UI styling
- `scripts/`: import tools for broker XLSX files and helper scripts

## Operating Notes

- Korean market names/prices should use Naver Finance where available.
- US and HK symbols generally use Yahoo Finance.
- HK tickers should normalize to the 4 digit form for display, while Yahoo lookup may need `.HK`.
- SELL events should allocate to existing BUY lots; sells with no prior lot should not be blindly imported.
- Cashflow is cash only. Portfolio value and cash balance should not be mixed without clear labels.
- Keep table UX dense and spreadsheet-like. This app is used repeatedly, not as a landing page.

## For A New Codex Or Antigravity Session

Start by reading:

```bash
git status --short
git log --oneline -5
README.md
handoff.md
```

Then inspect only the files relevant to the requested task.

Before editing, make the pre-work backup commit if there are local changes. After editing and verification, make the post-work commit and push.

