# Trading Journal Production Rollout Design

**Date:** 2026-06-21

**Scope:** Git integration, runtime-data protection, friend-server service migration, and `tjgyu.site` publication

**Out of scope:** KIS credential setup and KIS staged rollout, which remain governed by `docs/KIS_SYNC_RUNBOOK.md`

## 1. Goal

Move the verified Trading Journal UI onto the intended friend-server checkout at `/opt/gyu/trading_journal`, preserve the current runtime data, expose the application through `https://tjgyu.site`, and leave a Git-tracked record that another Codex or Gemini session can follow without relying on chat history.

The rollout is complete only when:

1. the verified UI branch is integrated into remote `main` without force-pushing;
2. `.env.runtime`, `data/db.sqlite`, and `data/uploads` have recoverable pre-deployment backups outside Git;
3. `trading-journal.service` starts from `/opt/gyu/trading_journal`, is enabled at boot, and survives a restart;
4. `tjgyu.site` resolves publicly through a Cloudflare Tunnel and loads the application over HTTPS;
5. local and external smoke checks pass and the outcome is recorded in tracked documentation.

## 2. Current State and Constraints

The rollout starts from these observed facts:

- Current branch: `fix/ui-theme-chart-lifecycle`.
- Current local HEAD: `fda4d5d`, one commit ahead of `origin/fix/ui-theme-chart-lifecycle` when inspected.
- The active systemd service is still running the older checkout under `/home/soso6079/projects/websites/trading_journal`.
- Port `127.0.0.1:8000` is active, but it is served by that older checkout.
- `cloudflared` is not installed and no Cloudflare systemd unit exists.
- `tjgyu.site` does not currently resolve from the friend server.
- The intended runtime files already exist under `/opt/gyu/trading_journal`.
- Non-interactive `sudo` is unavailable, so administrator commands require the human to enter the server sudo password.

The following paths must never be staged or committed:

- `.env.runtime`
- `.env.kis`
- `data/db.sqlite`
- `data/uploads/`
- backup archives or copied secrets
- the existing unrelated untracked workspace files
- `tests/test_japan_market.py`

## 3. Rollout Architecture

The deployment uses GitHub for code and documentation only. Runtime state stays on the friend server and is backed up to a timestamped directory below `/opt/gyu/backups/`. The systemd web service runs Uvicorn as `gyu123:gyuedit`, binds only to `127.0.0.1:8000`, and loads secrets from `/opt/gyu/trading_journal/.env.runtime`.

Cloudflare Tunnel is the only public ingress. It maps `tjgyu.site` to the loopback web service, so the application port is not opened directly to the internet. The public DNS record is managed by Cloudflare and must be proxied through the tunnel.

Every phase follows the same control loop:

1. inspect Git and runtime state;
2. create or confirm the rollback point;
3. make one bounded change;
4. verify the change locally;
5. record non-secret evidence in Git;
6. commit before advancing.

## 4. Agent Responsibility Split

### Codex-owned work

Codex owns operations where a mistake can affect source history, availability, credentials, or public routing:

- author and maintain the rollout plan and handoff record;
- review every Gemini patch before it is committed;
- push the UI branch and integrate it into `main`;
- create and verify runtime backups without exposing their contents;
- install dependencies required by the intended checkout;
- replace and restart the systemd service;
- install and configure Cloudflare Tunnel;
- create or verify the Cloudflare DNS route;
- perform rollback if a production check fails;
- run the final acceptance checks and produce the final Git commit.

### Gemini-owned work

Gemini receives deterministic, reversible work that Codex can review from a diff or command transcript:

- correct stale non-secret deployment paths in `docs/FRIEND_SERVER_HANDOFF.md`;
- align documentation with the committed service and Cloudflare templates;
- run the prescribed automated test command while excluding `tests/test_japan_market.py`;
- run browser smoke checks for `/journal`, `/portfolio`, and `/stats` after Codex starts the intended service;
- check for duplicate chart rendering, theme-switch regressions, and browser console errors;
- add its non-secret observations to the tracked rollout handoff section;
- stop and hand control back to Codex if any command needs sudo, Cloudflare authentication, Git integration, runtime-data mutation, or secret access.

Gemini must not run concurrently in the same files while Codex is editing them. Work is handed off by commit SHA, and the receiving agent starts by running `git status --short --branch` and `git log --oneline -5`.

## 5. Phase Design

### Phase A: Git integration

Codex confirms the feature branch contains only intended UI changes, reruns the test suite, pushes the feature branch, updates local `main` by fast-forwarding from `origin/main`, merges the feature branch without rewriting history, reruns verification, and pushes `main`.

No deployment begins if the feature branch or merge verification fails. Existing unrelated untracked files remain untouched.

### Phase B: Runtime backup and data protection

Codex creates a timestamped backup outside the repository containing the current database, uploads directory, runtime environment file, and existing systemd unit. Verification records filenames, file types, sizes, permissions, and checksums where safe; it never records secret values.

The source runtime files are copied, not moved. The database remains the server source of truth. No historical import or KIS activation is part of this rollout.

### Phase C: Friend-server service migration

Codex installs the application dependencies for `/opt/gyu/trading_journal`, resolves the actual Uvicorn executable path, and installs a systemd unit whose `WorkingDirectory` and `EnvironmentFile` reference that checkout. The unit remains bound to loopback and runs as `gyu123:gyuedit`.

The old service is replaced only after the new checkout can import the application successfully. After restart, acceptance requires an active/enabled service, the expected process working directory, a successful `/access` response, and journal/portfolio/stats page checks. A failed check triggers restoration of the backed-up unit and service restart.

### Phase D: Domain publication

Codex installs `cloudflared` from an official Cloudflare package source, authenticates or uses a user-provided scoped tunnel credential, creates a dedicated tunnel for Trading Journal, and routes `tjgyu.site` to `http://127.0.0.1:8000`.

The tunnel runs as a dedicated enabled systemd service. Public acceptance requires DNS resolution, a valid HTTPS response, no direct public listener on port 8000, and successful access from a network outside the server. If DNS propagation prevents immediate external validation, the rollout record must say that publication is pending rather than claim completion.

## 6. Error Handling and Rollback

- Git conflicts: abort the merge, leave both branches intact, document the conflicting paths, and resolve only after review.
- Test failure: do not push `main` or restart production until the regression is understood.
- Backup verification failure: stop before replacing the service.
- New service failure: restore the backed-up systemd unit, reload systemd, and restart the old service.
- Tunnel failure: leave the loopback web service running, disable only the tunnel unit, and preserve the tunnel diagnostics without credentials.
- DNS delay: keep the service and tunnel running if locally healthy, record the pending external check, and do not mark the domain phase complete.

No rollback may replace `data/db.sqlite` automatically. Database restoration requires explicit human approval because it can discard newer journal entries.

## 7. Verification Strategy

Automated verification uses the project test suite while excluding `tests/test_japan_market.py`, followed by import and HTTP smoke checks. Browser verification covers:

- `/journal`, `/portfolio`, and `/stats` render without visible errors;
- each stats chart has exactly one rendered chart instance;
- dark/light theme switching updates page and chart colors without duplicate rendering;
- browser console contains no application errors;
- admin authentication and image upload are checked without recording tokens or uploaded private content.

Operational verification covers:

- Git branch and remote SHAs;
- sensitive paths absent from the staged file list;
- backup existence and metadata;
- systemd enabled/active state and process working directory;
- local `/access` response;
- Cloudflare service enabled/active state;
- public DNS and HTTPS response;
- reboot restoration, performed only after all non-reboot checks pass.

## 8. Git-tracked Handoff Contract

The implementation plan will define a tracked rollout record containing:

- phase status: pending, in progress, complete, or blocked;
- commit SHAs used for handoffs;
- exact verification commands and summarized outcomes;
- backup directory path without secret contents;
- systemd and Cloudflare unit names;
- any human action still required;
- rollback point and final acceptance status.

An agent may mark a phase complete only from fresh command output. Planned commands, copied documentation, or assumptions are not completion evidence.
