# KIS Read-only Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Korea Investment & Securities execution collector that safely reconciles domestic, US, and Hong Kong fills into the existing Journal without any order capability.

**Architecture:** A dedicated KIS client normalizes official REST responses into broker-neutral execution snapshots. A database-backed reconciler stores every snapshot, applies only positive cumulative-fill deltas, and creates Journal events through the existing buy/sell services. A separate worker performs startup and periodic reconciliation; the web app only exposes admin status, pause/resume, manual synchronization, and pending SELL allocation.

**Tech Stack:** Python 3.11+, FastAPI, SQLModel/SQLite, urllib, optional websockets, unittest, systemd, Cloudflare Tunnel.

---

### Task 1: Configuration and normalized execution contract

**Files:**
- Create: `app/kis_config.py`
- Create: `app/kis_client.py`
- Test: `tests/test_kis_config.py`
- Test: `tests/test_kis_client.py`

- [ ] Write failing tests for safe defaults, order-disable enforcement, account hashing, domestic/overseas market mapping, numeric parsing, and fill-only normalization.
- [ ] Run the focused tests and confirm imports fail because the modules do not exist.
- [ ] Implement `.env.kis` loading, immutable settings, OAuth/approval token calls, paginated domestic/overseas inquiries, and response normalization.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Persistence and idempotent reconciliation

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py`
- Modify: `app/services.py`
- Create: `app/kis_sync.py`
- Test: `tests/test_kis_sync.py`

- [ ] Write failing tests proving repeated snapshots create one Event, cumulative quantity creates only the delta, SELL uses FIFO lots, and an unallocatable SELL remains pending.
- [ ] Run the focused tests and confirm failure for missing models/reconciler.
- [ ] Add broker execution/state tables and Event provenance columns with compatible SQLite migration.
- [ ] Implement transactional ingestion and Journal event application through existing services.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Worker and administrator controls

**Files:**
- Create: `scripts/kis_sync_worker.py`
- Create: `app/templates/broker_sync.html`
- Modify: `app/main.py`
- Modify: `app/templates/base.html`
- Modify: `app/static/style.css`
- Test: `tests/test_kis_admin.py`

- [ ] Write failing tests for status serialization, pause state, and manual-sync eligibility.
- [ ] Implement startup seven-day reconciliation, 60-second polling, daily full reconciliation, pause handling, and optional WebSocket wake signals.
- [ ] Add admin-only status page and APIs for manual sync, pause/resume, and pending SELL review.
- [ ] Run focused and full tests.

### Task 4: Security and operations handoff

**Files:**
- Modify: `.gitignore`
- Create: `.env.kis.example`
- Create: `deploy/trading-journal.service.example`
- Create: `deploy/trading-journal-kis-sync.service.example`
- Create: `deploy/cloudflared-config.example.yml`
- Create: `docs/KIS_SYNC_RUNBOOK.md`
- Modify: `handoff.md`

- [ ] Ensure `.env.kis`, token cache, databases, uploads, and runtime bundles are ignored.
- [ ] Document credential setup, staged paper/real rollout, DB/import backups, service installation, Tunnel/DNS setup, secret rotation, and verification commands.
- [ ] Scan the codebase to prove no KIS order endpoint or order method exists.
- [ ] Compile the app, run all unit tests, inspect Git diff, and commit the feature branch.

