# Friend Server Handoff

## 1) Code Sync (friend server)

```bash
cd /opt/gyu/trading_journal
git fetch origin
git checkout main
git pull --ff-only origin main
```

## 2) Runtime Files To Transfer

Do **not** put these on public GitHub:

- `data/db.sqlite`
- `data/uploads/`
- `.env.runtime`

If you need one bundle from local PC:

```powershell
cd "D:\주식\trading_journal"
Compress-Archive -Path ".env.runtime","data\\db.sqlite","data\\uploads" -DestinationPath "runtime_bundle.zip" -Force
```

Transfer `runtime_bundle.zip` to friend server and extract in project root:

```bash
cd /opt/gyu/trading_journal
unzip -o runtime_bundle.zip
```

## 3) Python Environment (friend server)

```bash
cd /opt/gyu/trading_journal
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
```

If the project uses Poetry on server:

```bash
cd /opt/gyu/trading_journal
poetry install
```

Use either `venv` or `poetry`, not both.

## 4) Run App

```bash
cd /opt/gyu/trading_journal
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 5) Quick Verify

```bash
curl -I http://127.0.0.1:8000/access
```

Expected: HTTP 200 or redirect response.

## 6) Production Service Verification

Verify the systemd service with these commands:

```bash
systemctl is-enabled trading-journal.service
systemctl is-active trading-journal.service
systemctl show -p MainPID --value trading-journal.service
curl -fsS http://127.0.0.1:8000/access >/dev/null
```

Note: The intended systemd unit template is `deploy/trading-journal.service.example`. The public endpoint is provided only through Cloudflare Tunnel.

## 7) Current Feature Context

- Journal now has `Missed High` metric for SELL events.
- Same-day trades (`buy_date == sell_date`) are excluded and marked with an icon.
- KR high source: Naver daily high.
- US/HK high source: Yahoo daily high.

