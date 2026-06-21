# Trading Journal Handoff

This file is the working handoff for Codex, Google Antigravity, and any other machine that continues this project.

## Project

- App: personal trading journal, portfolio, and stats web app
- Stack: Python 3.11+, FastAPI, SQLModel, SQLite, Jinja2
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

- **Operational Path**: `/opt/gyu/trading_journal`
- **Public URL**: `https://tjgyu.site`
- **Active Web Service**: `trading-journal.service`
  - WorkingDirectory: `/opt/gyu/trading_journal`
  - ExecStart: `/opt/gyu/trading_journal/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **New Tunnel Service**: `cloudflared.service`
  - Runs under user `gyu123` and group `gyuedit`.
  - Service file: `/etc/systemd/system/cloudflared.service`
  - ExecStart: `/usr/bin/cloudflared tunnel --config /etc/cloudflared/config.yml run 263386ee-cdcc-4b4c-9a57-dc04e0bae4fb`
- **Legacy Service Boundary**:
  - The pre-existing `cloudflared-trading-journal.service` (running under user `soso6079`) manages 4 active legacy sites (`trading-journal.work`, `reports`, `terminal`, `betawavve`).
  - **CRITICAL**: Do **NOT** modify, stop, or disable `cloudflared-trading-journal.service` or its `/home/soso6079/.cloudflared/config.yml` config.
- **Reboot Recovery status**:
  - Currently **DEFERRED (PENDING)**.
  - Reason: The shared server runs active long-term workloads (Codex/Grok agents in `soso6079`'s tmux sessions) and database services run inside the `kis-runtime` LXD container (whose autostart has not yet been verified post-reboot).
  - Rebooting requires prior coordination with the server owner.
- **KIS Integration**:
  - The KIS client and synchronization architecture are ready, but activation/execution of KIS sync runs is a **separate step** that is not currently enabled.


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

# KIS read-only synchronization

The KIS integration architecture, staged rollout, service installation, domain connection, backup, and rollback procedures are documented in `docs/KIS_SYNC_RUNBOOK.md`. The non-negotiable safety boundary is read-only execution collection: do not add KIS order endpoints to this service. `KIS_ORDER_ENABLED` must remain `false`.

Before and after every server or feature change:

1. Check `git status` and create a checkpoint commit containing code only.
2. Back up the server DB and uploads outside Git.
3. Work on a feature branch and run the full test suite.
4. Commit the verified result before merging to `main`.

# UI/UX Modernization (2026-06-19)

A comprehensive UI/UX refactoring was completed to enhance the trading journal's aesthetics and user interface flow.

## Implemented Changes

1. **Theme System**:
   - Switched to HSL-based dynamic colors.
   - Default is a dark theme (Navy/Charcoal background). A toggle button in the top bar switches to light mode.
   - Theme preference is saved locally (`localStorage.getItem("tj-theme")`).
   - Prevents white flash via an IIFE in `base.html` `<head>`.
2. **Form Layout (Slide-out Drawers)**:
   - Moved BUY, SELL, CASHFLOW, and SL_UPDATE forms to right-hand drawers (`.drawer` in CSS).
   - Added a compact `.quick-action-bar` at the top of the Journal page with custom buttons to slide drawers open.
   - Main page now defaults to a clean table view without showing giant forms at the top.
3. **Data Visualization (ApexCharts)**:
   - Removed yfinance dependency and SVG string builders in `stats.html`.
   - Integrated `ApexCharts` CDN in `base.html`.
   - Rendered Area/Line and Column mixed charts with smooth curves, gradients, and tooltips.
   - Handled `theme-change` event dynamically to redraw/update charts when theme switches.

## Verification
- Run local server to view:
  ```powershell
  cd "D:\주식\trading_journal"
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
  ```
- Make sure to review `docs/superpowers/plans/2026-06-19-ui-ux-modernization-design.md` for technical design details.
