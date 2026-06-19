# KIS Read-only Sync Runbook

## Safety contract

- This integration only calls OAuth, WebSocket approval, domestic fill inquiry, and overseas fill inquiry endpoints.
- It contains no order endpoint and rejects `KIS_ORDER_ENABLED=true` at startup.
- WebSocket notices only wake the REST reconciler. REST responses are the authoritative source.
- Keep `.env.runtime`, `.env.kis`, `data/db.sqlite`, `data/uploads`, and runtime bundles outside Git.

## 1. Back up before every deployment

Run on the friend server:

```bash
cd /opt/gyu/trading_journal
stamp=$(date +%Y%m%d_%H%M%S)
mkdir -p /opt/gyu/backups/$stamp
cp data/db.sqlite /opt/gyu/backups/$stamp/db.sqlite
cp -a data/uploads /opt/gyu/backups/$stamp/uploads
cp .env.runtime /opt/gyu/backups/$stamp/.env.runtime
sudo cp /etc/systemd/system/trading-journal.service /opt/gyu/backups/$stamp/ 2>/dev/null || true
sudo cp /etc/systemd/system/trading-journal-kis-sync.service /opt/gyu/backups/$stamp/ 2>/dev/null || true
```

Create a Git checkpoint before edits:

```bash
git status --short
git add -A
git commit -m "chore: checkpoint before deployment" || true
```

Do not stage runtime secrets or data. Confirm with `git status --short --ignored`.

## 2. Restore missing Mirae Asset history

Provide these files before importing:

- Domestic executions including `2026-03-06` and later.
- Overseas executions including `2026-02-25` and later.
- Cash deposits/withdrawals after `2026-02-25`.
- Current domestic and overseas holdings snapshots.

Use the existing importer in dry-run mode first. Back up the DB, import, then compare KR/US/HK quantities and cash against the holdings snapshots. The import is not complete until all four reconcile. The server DB is the source of truth; never replace it with an older local DB.

## 3. Install code and services

The server administrator runs:

```bash
cd /opt/gyu/trading_journal
git fetch origin
git switch main
git pull --ff-only origin main
python3 -m pip install --user --break-system-packages -e .
sudo install -m 0644 deploy/trading-journal.service.example /etc/systemd/system/trading-journal.service
sudo install -m 0644 deploy/trading-journal-kis-sync.service.example /etc/systemd/system/trading-journal-kis-sync.service
sudo systemctl daemon-reload
sudo systemctl enable --now trading-journal.service
```

Do not start the KIS worker until `.env.kis` is configured and paper credentials have been tested.

## 4. Configure KIS secrets

```bash
cd /opt/gyu/trading_journal
cp .env.kis.example .env.kis
chmod 600 .env.kis
nano .env.kis
```

Start with:

```env
KIS_ENV=paper
KIS_SYNC_ENABLED=true
KIS_WRITE_EVENTS=false
KIS_ORDER_ENABLED=false
```

Then start and inspect the worker:

```bash
sudo systemctl enable --now trading-journal-kis-sync.service
sudo systemctl status trading-journal-kis-sync.service --no-pager
journalctl -u trading-journal-kis-sync.service -n 100 --no-pager
```

Logs intentionally omit account numbers, App Secrets, access tokens, and raw payloads.

## 5. Staged rollout

1. Keep paper `KIS_WRITE_EVENTS=false` for five trading days and compare collected executions with the KIS screen.
2. Back up the DB, set paper `KIS_WRITE_EVENTS=true`, restart the worker, and test BUY, SELL, partial fill, duplicate REST fetch, and service restart.
3. Set `KIS_ENV=real`, real credentials, and `KIS_WRITE_EVENTS=false` for three trading days.
4. Require 100% execution agreement before setting real `KIS_WRITE_EVENTS=true`.
5. For the first two weeks, compare executions, holdings, and Journal every day after market close.
6. On any mismatch, use the KIS Sync admin page to pause writes. Preserve all BrokerExecution rows.

## 6. Cloudflare Tunnel and root domain

Copy `deploy/cloudflared-config.example.yml` to the existing cloudflared configuration and replace the Tunnel UUID. The administrator then validates and restarts cloudflared. Create the root hostname route:

```bash
cloudflared tunnel route dns REPLACE_WITH_TUNNEL_NAME tjgyu.site
sudo systemctl restart cloudflared-trading-journal.service
```

Cloudflare DNS should contain a proxied CNAME for `@` pointing to the Tunnel hostname. Verify from mobile data, not the home Wi-Fi:

- `https://tjgyu.site/access` loads.
- Admin login works.
- Journal edit and image upload work.
- Rebooting the server restores web and worker services.

## 7. Rotate previously exposed application secrets

Generate new signing, viewer, and admin tokens on the server, replace `.env.runtime`, generate a new administrator password hash with the project helper documented in `README.md`, increment `TJ_AUTH_VERSION`, and restart the web service. Never paste the new values into chat or Git.

## 8. Verification and rollback

```bash
curl -fsS http://127.0.0.1:8000/access >/dev/null
systemctl is-active trading-journal.service
systemctl is-active trading-journal-kis-sync.service
python3 -m unittest discover -s tests -v
grep -RniE '/uapi/.+(order|ordr)|KIS_ORDER_ENABLED=true' app scripts || true
```

To roll back, stop both services, restore the DB/uploads and service files from `/opt/gyu/backups/<timestamp>`, run `systemctl daemon-reload`, and restart the services.
