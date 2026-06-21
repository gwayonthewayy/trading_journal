# Trading Journal Production Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the verified UI work into remote `main`, protect the friend-server runtime state, migrate the always-on web service to `/opt/gyu/trading_journal`, and publish it safely at `https://tjgyu.site`.

**Architecture:** GitHub carries code and non-secret operational evidence; runtime data remains outside Git under `/opt/gyu/trading_journal` with a verified pre-deployment backup under `/opt/gyu/backups`. Systemd runs Uvicorn from the repository virtual environment on loopback, and a locally managed Cloudflare Tunnel is the only public ingress. Codex owns all high-risk mutations; Gemini performs bounded documentation and browser-verification passes between Codex checkpoints.

**Tech Stack:** Git/GitHub, Python 3.12 virtualenv, FastAPI/Uvicorn, unittest, systemd, Cloudflare Tunnel, Ubuntu 24.04, SQLite, browser developer tools.

---

## Execution Rules and Ownership

- Execute tasks in order. Codex and Gemini must not work in this checkout concurrently.
- Every handoff starts with `git status --short --branch` and `git log --oneline -5`.
- Codex reviews all Gemini diffs before committing them.
- Never stage or commit `.env.runtime`, `.env.kis`, `data/db.sqlite`, `data/uploads/`, backups, credentials, tokens, or the existing unrelated untracked workspace files.
- Do not edit `tests/test_japan_market.py`. Its existing commits may enter `main` when the current branch is merged, but this rollout must not change the file.
- Never force-push or rewrite a pushed commit.
- Do not replace or restore the production database without explicit human approval.
- `.env.runtime` is read only for this rollout. Secret rotation is a separate human-managed task because the workspace instruction forbids modifying it.
- Commands requiring sudo are human-assisted Codex steps: Codex prepares and explains the exact command, and the human enters the sudo password directly in a terminal. Passwords and Cloudflare credentials never enter chat or Git.
- Use `docs/operations/2026-06-21-production-rollout-log.md` as the non-secret execution record. Update and commit it after each completed phase.

## Verified Starting Point

- Branch: `fix/ui-theme-chart-lifecycle`
- Design commit: `54e52e1`
- UI repair commit: `fda4d5d`
- Remote comparison at planning time: local branch is two commits ahead of `origin/fix/ui-theme-chart-lifecycle`
- Active web unit: `trading-journal.service`
- Active unit currently points to `/home/soso6079/projects/websites/trading_journal`
- Intended checkout: `/opt/gyu/trading_journal`
- Intended local origin: `http://127.0.0.1:8000`
- `cloudflared` is not installed at planning time
- `tjgyu.site` does not resolve at planning time
- Server OS: Ubuntu 24.04 Noble

### Task 1: Pin the tracked systemd template to the project virtualenv

**Owner:** Codex

**Files:**
- Create: `tests/test_deploy_templates.py`
- Modify: `deploy/trading-journal.service.example`

- [ ] **Step 1: Confirm the protected worktree state**

Run:

```bash
git status --short --branch
git log --oneline -5
```

Expected: only the previously known untracked workspace files are listed; no runtime file or `tests/test_japan_market.py` is modified.

- [ ] **Step 2: Prepare the ignored repository virtualenv for tests**

Run:

```bash
python3 -m venv --upgrade-deps .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -c 'import fastapi, sqlmodel, uvicorn; print("deps_ok")'
```

Expected: `deps_ok`. The `.venv/` directory remains ignored and absent from `git status`.

- [ ] **Step 3: Write the failing deployment-template test**

Create `tests/test_deploy_templates.py` with:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployTemplateTests(unittest.TestCase):
    def test_web_service_uses_intended_checkout_and_project_venv(self):
        unit = (ROOT / "deploy" / "trading-journal.service.example").read_text(encoding="utf-8")

        self.assertIn("User=gyu123", unit)
        self.assertIn("Group=gyuedit", unit)
        self.assertIn("WorkingDirectory=/opt/gyu/trading_journal", unit)
        self.assertIn("EnvironmentFile=/opt/gyu/trading_journal/.env.runtime", unit)
        self.assertIn(
            "ExecStart=/opt/gyu/trading_journal/.venv/bin/uvicorn "
            "app.main:app --host 127.0.0.1 --port 8000",
            unit,
        )
        self.assertNotIn("/home/soso6079", unit)
        self.assertNotIn("--host 0.0.0.0", unit)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the test and confirm the current template fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_deploy_templates -v
```

Expected: FAIL because the current template uses `/home/gyu123/.local/bin/uvicorn` instead of the project virtualenv.

- [ ] **Step 5: Correct the service executable**

Replace the `ExecStart` line in `deploy/trading-journal.service.example` with:

```ini
ExecStart=/opt/gyu/trading_journal/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 6: Run the focused test and protected suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_deploy_templates -v
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
```

Expected: the deployment-template test passes and every selected test passes. Record the test count; do not run or edit `tests/test_japan_market.py`.

- [ ] **Step 7: Commit the bounded configuration fix**

Run:

```bash
git add deploy/trading-journal.service.example tests/test_deploy_templates.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix(deploy): run web service from project venv"
```

Expected staged paths: exactly the two files named above.

### Task 2: Normalize handoff documentation and establish the rollout log

**Owner:** Gemini writes and verifies; Codex reviews and commits.

**Files:**
- Modify: `docs/FRIEND_SERVER_HANDOFF.md`
- Create: `docs/operations/2026-06-21-production-rollout-log.md`

- [ ] **Step 1: Gemini confirms the Codex checkpoint**

Run:

```bash
git status --short --branch
git log --oneline -5
git show --stat --oneline HEAD
```

Expected: HEAD is Task 1's `fix(deploy)` commit and no tracked file is modified.

- [ ] **Step 2: Gemini corrects stale friend-server commands**

In `docs/FRIEND_SERVER_HANDOFF.md`:

1. Replace every `cd ~/trading_journal` with `cd /opt/gyu/trading_journal`.
2. Keep the venv path as `.venv`, but use `.venv/bin/python -m pip` for installation commands.
3. Replace the manual bind address `0.0.0.0` with `127.0.0.1`.
4. Add a production-service verification section containing exactly these commands:

```bash
systemctl is-enabled trading-journal.service
systemctl is-active trading-journal.service
systemctl show -p MainPID --value trading-journal.service
curl -fsS http://127.0.0.1:8000/access >/dev/null
```

5. State that the intended unit template is `deploy/trading-journal.service.example` and that the public endpoint is provided only through Cloudflare Tunnel.

- [ ] **Step 3: Gemini creates the initial non-secret execution record**

Create `docs/operations/2026-06-21-production-rollout-log.md` with:

```markdown
# Production Rollout Log — 2026-06-21

## Safety boundary

- Runtime secrets and data remain outside Git.
- `.env.runtime`, `data/db.sqlite`, and `data/uploads/` are not modified by documentation or Git tasks.
- `tests/test_japan_market.py` is not modified or executed by this rollout.
- Database restoration requires explicit human approval.

## Agent handoff

- Design commit: `54e52e1`
- Current owner: Codex
- Execution model: sequential Codex/Gemini handoffs; never concurrent edits

## Phase status

- Git integration: planned
- Runtime backup: planned
- Friend-server service migration: planned
- Local browser acceptance: planned
- Cloudflare Tunnel and DNS: planned
- External acceptance and reboot recovery: planned

## Evidence

Execution has not started. Each phase will be updated only from fresh command output.
```

- [ ] **Step 4: Gemini runs the protected baseline suite**

Run:

```bash
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
```

Expected: all selected tests pass. Gemini adds the UTC time, command, test count, and PASS result to the Evidence section without copying secrets or raw application data.

- [ ] **Step 5: Gemini leaves a reviewable diff and hands back to Codex**

Run:

```bash
git diff --check
git diff -- docs/FRIEND_SERVER_HANDOFF.md docs/operations/2026-06-21-production-rollout-log.md
git status --short --branch
```

Gemini must not stage or commit. It reports the two changed paths and stops.

- [ ] **Step 6: Codex reviews and commits Gemini's work**

Codex checks the diff against this task, confirms no other tracked path changed, then runs:

```bash
git add docs/FRIEND_SERVER_HANDOFF.md docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: prepare friend-server rollout handoff"
```

Expected staged paths: exactly the two documentation files.

### Task 3: Push the feature branch and integrate it into remote main

**Owner:** Codex

**Files:**
- Modify after merge: `docs/operations/2026-06-21-production-rollout-log.md`

This task merges the complete existing branch history, including previously completed corporate-action and Japan-support commits. It does not edit `tests/test_japan_market.py`.

- [ ] **Step 1: Fetch and verify branch scope**

Run:

```bash
git status --short --branch
git fetch --prune origin
git log --reverse --oneline origin/main..HEAD
git diff --name-status origin/main...HEAD
```

Expected: no unexpected new tracked change appears. The design, plan, deployment-template, documentation, and previously completed feature commits are visible.

- [ ] **Step 2: Run the merge-gate tests**

Run:

```bash
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
```

Expected: all selected tests pass.

- [ ] **Step 3: Push the current feature branch without rewriting history**

Run:

```bash
git push origin fix/ui-theme-chart-lifecycle
git status --short --branch
```

Expected: local and remote feature branches point to the same commit. Existing unrelated untracked files remain local.

- [ ] **Step 4: Fast-forward local main, then merge the feature branch**

Run:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff fix/ui-theme-chart-lifecycle -m "merge: integrate verified UI and rollout preparation"
```

Expected: merge completes without conflict. If any conflict occurs, run `git merge --abort`, record the conflicting paths, and stop for review.

- [ ] **Step 5: Verify the merge and protected files**

Run:

```bash
git status --short --branch
git log --graph --decorate --oneline -15
git diff HEAD^1..HEAD -- .env.runtime data/db.sqlite data/uploads
git log --format='%h %s' -- tests/test_japan_market.py
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
```

Expected: runtime paths have no Git diff, the Japan test log contains only the pre-existing `eec53f1` and `fb4a055` commits, and all selected tests pass.

- [ ] **Step 6: Push main and record the integration SHA**

Run:

```bash
git push origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected: both SHAs match.

Update the rollout log:

- mark Git integration `complete`;
- record the merge SHA and feature-branch tip;
- record the selected test count and PASS result;
- state that no runtime file was staged.

Then run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --check
git commit -m "docs(ops): record main integration"
git push origin main
```

### Task 4: Create and verify the pre-deployment runtime backup

**Owner:** Codex

**Files:**
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`
- Runtime output outside Git: a dynamically timestamped directory below `/opt/gyu/backups/`
- Stable rollback link outside Git: `/opt/gyu/backups/trading-journal-predeploy-current`

- [ ] **Step 1: Verify the protected sources without displaying contents**

Run:

```bash
cd /opt/gyu/trading_journal
for path in .env.runtime data/db.sqlite data/uploads; do stat -c '%n|%F|mode=%a|owner=%U:%G|size=%s' "$path"; done
systemctl cat trading-journal.service
git status --short --branch
```

Expected: all runtime paths exist, the current unit is readable, and Git shows no runtime file.

- [ ] **Step 2: Create a transaction-safe timestamped backup**

Run:

```bash
BACKUP_DIR="/opt/gyu/backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_DIR"
.venv/bin/python -c 'import sqlite3, sys; src=sqlite3.connect("data/db.sqlite"); dst=sqlite3.connect(sys.argv[1]); src.backup(dst); dst.close(); src.close()' "$BACKUP_DIR/db.sqlite"
install -m 0600 .env.runtime "$BACKUP_DIR/.env.runtime"
cp -a data/uploads "$BACKUP_DIR/uploads"
install -m 0600 /etc/systemd/system/trading-journal.service "$BACKUP_DIR/trading-journal.service"
ln -sfn "$BACKUP_DIR" /opt/gyu/backups/trading-journal-predeploy-current
```

Expected: the source files remain in place and the stable link resolves to the new backup directory.

- [ ] **Step 3: Verify backup integrity without reading secrets into logs**

Run:

```bash
BACKUP_DIR=$(readlink -f /opt/gyu/backups/trading-journal-predeploy-current)
.venv/bin/python -c 'import sqlite3, sys; value=sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0]; print(value); raise SystemExit(value != "ok")' "$BACKUP_DIR/db.sqlite"
cmp --silent .env.runtime "$BACKUP_DIR/.env.runtime"
diff -qr data/uploads "$BACKUP_DIR/uploads"
stat -c '%n|%F|mode=%a|owner=%U:%G|size=%s' "$BACKUP_DIR/db.sqlite" "$BACKUP_DIR/.env.runtime" "$BACKUP_DIR/uploads" "$BACKUP_DIR/trading-journal.service"
```

Expected: SQLite prints `ok`, `cmp` and `diff` exit successfully, and all four backup items exist.

- [ ] **Step 4: Record and commit non-secret backup evidence**

Update the rollout log with the backup directory path, UTC time, SQLite integrity result, and file metadata. Do not record hashes of secrets, environment values, tokens, account data, or database rows.

Run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs(ops): record verified runtime backup"
git push origin main
```

Expected staged path: only the rollout log.

### Task 5: Build the project environment and migrate the systemd web service

**Owner:** Codex, with the human entering sudo credentials locally.

**Files:**
- Source template: `deploy/trading-journal.service.example`
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`
- System file: `/etc/systemd/system/trading-journal.service`

- [ ] **Step 1: Build the intended checkout before touching the live unit**

Run:

```bash
cd /opt/gyu/trading_journal
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -c 'from app.main import app; print(app.title)'
test -x .venv/bin/uvicorn
```

Expected: the app imports successfully and `.venv/bin/uvicorn` is executable.

- [ ] **Step 2: Run the protected suite from the production virtualenv**

Run:

```bash
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
```

Expected: all selected tests pass before downtime begins.

- [ ] **Step 3: Human-assisted installation of the tracked unit**

The human runs these commands in the server terminal and enters the sudo password there:

```bash
cd /opt/gyu/trading_journal
sudo install -m 0644 deploy/trading-journal.service.example /etc/systemd/system/trading-journal.service
sudo systemctl daemon-reload
sudo systemctl enable trading-journal.service
sudo systemctl restart trading-journal.service
```

Expected: every command exits successfully. Do not continue after a failure.

- [ ] **Step 4: Verify the service identity and local HTTP path**

Run:

```bash
systemctl is-enabled trading-journal.service
systemctl is-active trading-journal.service
systemctl status trading-journal.service --no-pager -n 30
PID=$(systemctl show -p MainPID --value trading-journal.service)
readlink -f "/proc/$PID/cwd"
tr '\0' ' ' < "/proc/$PID/cmdline"
curl -fsS -o /dev/null -w 'access=%{http_code}\n' http://127.0.0.1:8000/access
ss -ltnp | rg '127\.0\.0\.1:8000'
```

Expected:

- enabled and active;
- working directory `/opt/gyu/trading_journal`;
- command uses `/opt/gyu/trading_journal/.venv/bin/uvicorn`;
- `/access` returns an HTTP success code or intentional redirect accepted by curl;
- port 8000 is bound only to `127.0.0.1`.

- [ ] **Step 5: Roll back the unit if any service check fails**

Do not restore the database. The human runs only:

```bash
BACKUP_DIR=$(readlink -f /opt/gyu/backups/trading-journal-predeploy-current)
sudo install -m 0644 "$BACKUP_DIR/trading-journal.service" /etc/systemd/system/trading-journal.service
sudo systemctl daemon-reload
sudo systemctl restart trading-journal.service
```

Then stop the rollout and record the failure.

- [ ] **Step 6: Record and commit the successful service migration**

Update the rollout log with the unit state, process working directory, executable path, local HTTP status, and rollback link. Do not copy the environment or process environment.

Run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --check
git commit -m "docs(ops): record web service migration"
git push origin main
```

### Task 6: Run local browser acceptance against the migrated service

**Owner:** Gemini verifies; the human performs login; Codex reviews and commits.

**Files:**
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`

- [ ] **Step 1: Gemini verifies the handoff and service before opening a browser**

Run:

```bash
git status --short --branch
git log --oneline -5
systemctl is-active trading-journal.service
curl -fsS -o /dev/null http://127.0.0.1:8000/access
```

Expected: clean tracked state, current `main`, active service, successful local response.

- [ ] **Step 2: Human authenticates without sharing credentials**

Open `http://127.0.0.1:8000/access` in the browser session Gemini will inspect. The human completes admin authentication directly. Gemini must not read `.env.runtime`, ask for a token, paste credentials into chat, or save credentials in the rollout log.

- [ ] **Step 3: Gemini checks the three required pages**

Visit, in order:

```text
http://127.0.0.1:8000/journal
http://127.0.0.1:8000/portfolio
http://127.0.0.1:8000/stats
```

Expected: each page renders its main content without an authentication loop, visible traceback, broken layout, or browser console error.

- [ ] **Step 4: Gemini checks chart lifecycle and theme switching**

On `/stats`, evaluate:

```javascript
const ids = [
  "chart-daily",
  "chart-weekly",
  "chart-monthly",
  "chart-yearly",
  "fx-chart",
  "chart-distribution",
  "chart-closed-dist",
  "chart-closed-return-dist",
];
Object.fromEntries(ids.map((id) => [
  id,
  document.querySelectorAll(`#${id} > .apexcharts-canvas`).length,
]));
```

Expected: every rendered chart holder reports exactly `1` and none reports more than `1`.

Record the current theme, click `#theme-toggle-btn`, wait until redraw settles, run the same chart-count expression again, and confirm:

- `document.documentElement.dataset.theme` changed;
- chart holders still have at most one ApexCharts canvas;
- chart colors changed with the theme;
- no new browser console error appeared.

Toggle once more and confirm the same conditions.

- [ ] **Step 5: Gemini records results and hands back without committing**

Add to the rollout log:

- UTC verification time;
- PASS/FAIL for journal, portfolio, and stats;
- chart canvas counts before and after both theme toggles;
- browser console error count;
- no credentials or private journal content.

Run:

```bash
git diff --check
git diff -- docs/operations/2026-06-21-production-rollout-log.md
git status --short --branch
```

Gemini stops without staging or committing.

- [ ] **Step 6: Codex reviews and commits the browser evidence**

Run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --check
git commit -m "docs(ops): record local browser acceptance"
git push origin main
```

### Task 7: Install Cloudflare Tunnel and publish tjgyu.site

**Owner:** Codex, with human authentication and sudo assistance.

**Files:**
- Source template: `deploy/cloudflared-config.example.yml`
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`
- System configuration: `/etc/cloudflared/config.yml`
- Private credential outside Git: the generated tunnel UUID JSON below `/home/gyu123/.cloudflared/`

Official references verified while planning:

- Cloudflare package repository: `https://pkg.cloudflare.com/index.html`
- Locally managed tunnel workflow: `https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/`

- [ ] **Step 1: Confirm the domain is delegated to Cloudflare**

Run:

```bash
dig +short NS tjgyu.site
```

Expected: two Cloudflare nameservers.

If the command returns nothing or non-Cloudflare nameservers, pause. The human adds `tjgyu.site` to the Cloudflare dashboard, copies the two nameservers assigned by Cloudflare, and changes the domain's nameservers at the registrar. Resume only after `dig +short NS tjgyu.site` returns the assigned Cloudflare nameservers. Do not store registrar or Cloudflare credentials in Git or chat.

- [ ] **Step 2: Human-assisted install from Cloudflare's stable Noble repository**

The human runs:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared noble main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install cloudflared
cloudflared --version
```

Expected: `cloudflared --version` succeeds. Use the stable repository, never the nightly repository.

- [ ] **Step 3: Human authenticates the local tunnel client**

Run as `gyu123`, not root:

```bash
cloudflared tunnel login
```

The human opens the displayed URL, signs into Cloudflare, and authorizes the `tjgyu.site` zone. Expected: `/home/gyu123/.cloudflared/cert.pem` is created. Never display or commit that file.

- [ ] **Step 4: Create one named tunnel and derive its UUID without guessing**

Run:

```bash
cloudflared tunnel list --output json
```

If no active tunnel named `trading-journal` exists, run:

```bash
cloudflared tunnel create trading-journal
```

Then derive and verify the UUID:

```bash
TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c 'import json,sys; rows=[row for row in json.load(sys.stdin) if row.get("name")=="trading-journal" and not row.get("deletedAt")]; assert len(rows)==1, rows; print(rows[0]["id"])')
test -f "/home/gyu123/.cloudflared/$TUNNEL_ID.json"
printf 'tunnel_id=%s\n' "$TUNNEL_ID"
```

The UUID is not a secret, but the JSON file is private and must remain outside Git.

- [ ] **Step 5: Install and validate the system tunnel configuration**

Run:

```bash
TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c 'import json,sys; rows=[row for row in json.load(sys.stdin) if row.get("name")=="trading-journal" and not row.get("deletedAt")]; assert len(rows)==1, rows; print(rows[0]["id"])')
cp deploy/cloudflared-config.example.yml /tmp/trading-journal-cloudflared.yml
sed -i "s/REPLACE_WITH_TUNNEL_UUID/$TUNNEL_ID/g" /tmp/trading-journal-cloudflared.yml
sudo install -d -m 0755 /etc/cloudflared
sudo install -m 0644 /tmp/trading-journal-cloudflared.yml /etc/cloudflared/config.yml
cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
```

Expected: configuration validation succeeds and the ingress points only to `http://127.0.0.1:8000` with a final `http_status:404` fallback.

- [ ] **Step 6: Create the DNS route and install the system service**

Run:

```bash
cloudflared tunnel route dns trading-journal tjgyu.site
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable cloudflared.service
sudo systemctl restart cloudflared.service
```

If the DNS route already exists and points to this tunnel, treat that message as idempotent success after verifying public resolution in the next step. Any different existing target requires review before replacement.

- [ ] **Step 7: Verify tunnel, DNS, HTTPS, and loopback-only origin**

Run:

```bash
systemctl is-enabled cloudflared.service
systemctl is-active cloudflared.service
systemctl status cloudflared.service --no-pager -n 40
cloudflared tunnel info trading-journal
dig +short NS tjgyu.site
dig +short A tjgyu.site
dig +short AAAA tjgyu.site
curl -fsS -o /dev/null -w 'https=%{http_code}\n' --retry 6 --retry-delay 10 https://tjgyu.site/access
ss -ltnp | rg ':8000'
```

Expected:

- Cloudflare service enabled and active;
- tunnel reports healthy connections;
- authoritative nameservers are Cloudflare and the apex resolves to Cloudflare addresses;
- HTTPS returns successfully after DNS propagation;
- port 8000 remains bound to `127.0.0.1`, not `0.0.0.0` or `::`.

If DNS propagation is incomplete, record the phase as `in progress`; do not claim completion.

- [ ] **Step 8: Isolate a failed tunnel without affecting the local web service**

If the tunnel service, DNS, or HTTPS check fails after installation, the human runs:

```bash
sudo systemctl disable --now cloudflared.service
systemctl is-active trading-journal.service
curl -fsS -o /dev/null http://127.0.0.1:8000/access
```

Expected: the public tunnel is inactive while the local Trading Journal remains healthy. Do not delete the tunnel, DNS record, or credential file automatically; record the failure for review.

- [ ] **Step 9: Record and commit non-secret publication evidence**

Update the rollout log with the cloudflared version, tunnel UUID, service state, Cloudflare nameservers, DNS result, HTTPS status, and UTC verification time. Do not record `cert.pem`, tunnel credential JSON, account IDs, API tokens, or dashboard screenshots containing secrets.

Run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --check
git commit -m "docs(ops): record domain publication"
git push origin main
```

### Task 8: Run external browser acceptance

**Owner:** Gemini verifies from an external network; the human authenticates; Codex reviews and commits.

**Files:**
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`

- [ ] **Step 1: Gemini verifies public availability without authentication**

From a network other than the friend server's local network, run:

```bash
curl -fsS -o /dev/null -w 'access=%{http_code}\n' https://tjgyu.site/access
```

Expected: successful HTTPS response with no certificate warning.

- [ ] **Step 2: Human authenticates in Gemini's external browser session**

Open `https://tjgyu.site/access`. The human completes admin authentication directly. Gemini must not receive or log the token/password.

- [ ] **Step 3: Gemini repeats full page, chart, theme, and console checks**

Visit:

```text
https://tjgyu.site/journal
https://tjgyu.site/portfolio
https://tjgyu.site/stats
```

Repeat Task 6's chart-count JavaScript and two theme toggles. Expected: the same PASS results over the public domain, no mixed-content error, and no browser console error.

- [ ] **Step 4: Gemini checks one reversible authenticated workflow**

Open the Journal edit UI for an existing row and cancel without submitting. Open the image-upload control and cancel without selecting a file. Expected: controls open correctly and no data is modified.

- [ ] **Step 5: Gemini records results and hands back without committing**

Record UTC time, external network type, page PASS/FAIL, chart counts, theme results, console error count, and reversible control checks. Do not record private row contents.

Run:

```bash
git diff --check
git diff -- docs/operations/2026-06-21-production-rollout-log.md
git status --short --branch
```

Gemini stops without staging or committing.

- [ ] **Step 6: Codex reviews and commits external evidence**

Run:

```bash
git add docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --check
git commit -m "docs(ops): record external browser acceptance"
git push origin main
```

### Task 9: Verify reboot recovery and close the rollout

**Owner:** Codex, with human approval for the reboot.

**Files:**
- Modify: `docs/operations/2026-06-21-production-rollout-log.md`
- Modify: `handoff.md`

- [ ] **Step 1: Confirm both services are enabled before reboot**

Run:

```bash
systemctl is-enabled trading-journal.service
systemctl is-active trading-journal.service
systemctl is-enabled cloudflared.service
systemctl is-active cloudflared.service
curl -fsS -o /dev/null http://127.0.0.1:8000/access
curl -fsS -o /dev/null https://tjgyu.site/access
```

Expected: all checks succeed.

- [ ] **Step 2: Human approves and initiates one controlled reboot**

The human runs:

```bash
sudo systemctl reboot
```

Expected: the session disconnects. Wait for the server to return; do not repeat the reboot command.

- [ ] **Step 3: Verify automatic recovery from fresh output**

After reconnecting, run:

```bash
systemctl is-active trading-journal.service
systemctl is-active cloudflared.service
PID=$(systemctl show -p MainPID --value trading-journal.service)
readlink -f "/proc/$PID/cwd"
curl -fsS -o /dev/null -w 'local=%{http_code}\n' http://127.0.0.1:8000/access
curl -fsS -o /dev/null -w 'public=%{http_code}\n' --retry 6 --retry-delay 10 https://tjgyu.site/access
systemctl show trading-journal.service -p ActiveState -p SubState -p NRestarts
systemctl show cloudflared.service -p ActiveState -p SubState -p NRestarts
```

Expected: both services are active in the new boot, the web process uses `/opt/gyu/trading_journal`, both HTTP checks succeed, and neither unit is in a restart loop.

- [ ] **Step 4: Update permanent handoff status**

In `handoff.md`, update the Friend Server section to state:

- production checkout is `/opt/gyu/trading_journal`;
- `trading-journal.service` runs the project `.venv` Uvicorn executable on `127.0.0.1:8000`;
- `cloudflared.service` publishes `https://tjgyu.site`;
- the rollout evidence is in `docs/operations/2026-06-21-production-rollout-log.md`;
- KIS activation remains a separate staged rollout.

Update the rollout log so every successful phase is `complete`, record reboot verification time, and list any genuinely pending item explicitly.

- [ ] **Step 5: Run final repository and application verification**

Run:

```bash
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"
git diff --check
git status --short --branch
git diff -- .env.runtime data/db.sqlite data/uploads tests/test_japan_market.py
```

Expected: all selected tests pass; only the intended two documentation files are modified; protected paths have no diff.

- [ ] **Step 6: Commit, push, and confirm remote completion**

Run:

```bash
git add handoff.md docs/operations/2026-06-21-production-rollout-log.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs(ops): complete production rollout handoff"
git push origin main
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: staged paths were exactly the two documentation files; local and remote main SHAs match; only the pre-existing unrelated untracked workspace files remain.

## Gemini Handoff Prompt

Use this prompt only at Task 2, Task 6, or Task 8 after Codex has committed the preceding checkpoint:

```text
Work in /opt/gyu/trading_journal and follow
docs/superpowers/plans/2026-06-21-production-rollout.md.

You are responsible only for the currently assigned Gemini task. Start with:
git status --short --branch
git log --oneline -5

Do not use sudo, modify Git history, stage or commit files, access secrets,
modify runtime data, or touch tests/test_japan_market.py. Do not work beyond
the assigned task. Run the listed verification, update only the listed
documentation file(s), show git diff --check and git status, then stop for
Codex review.
```
