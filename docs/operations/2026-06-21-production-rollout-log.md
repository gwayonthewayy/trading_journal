# Production Rollout Log — 2026-06-21

## Safety boundary

- Runtime secrets and data remain outside Git.
- `.env.runtime`, `data/db.sqlite`, and `data/uploads/` are not modified by documentation or Git tasks.
- `tests/test_japan_market.py` is not modified or executed by this rollout.
- Database restoration requires explicit human approval.

## Agent handoff

- Design commit: `54e52e1`
- Current owner: Gemini (Task 5 completed)
- Execution model: sequential Codex/Gemini handoffs; never concurrent edits

## Phase status

- Git integration: complete
- Runtime backup: complete
- Friend-server service migration: complete
- Local browser acceptance: planned
- Cloudflare Tunnel and DNS: planned
- External acceptance and reboot recovery: planned

## Evidence

### 2026-06-21T03:48:15Z - Task 2 (Gemini Baseline Verification)
- **Command:**
  ```bash
  mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
  .venv/bin/python -m unittest -v "${test_modules[@]}"
  ```
- **Outcome:** PASS (35 tests run, 0 failures, 0 errors)
- **Note:** `tests/test_japan_market.py` was correctly excluded and unmodified.

### 2026-06-21T03:49:19Z - Task 3 (Git Integration and Merging)
- **Merge SHA:** `d65e9c16510c082b9854cbb0d6213136ba9c85e8` (main)
- **Feature Branch Tip:** `a84d918` (`fix/ui-theme-chart-lifecycle`)
- **Test Command:**
  ```bash
  mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
  .venv/bin/python -m unittest -v "${test_modules[@]}"
  ```
- **Outcome:** PASS (35 tests run, 0 failures, 0 errors)
- **Note:** No runtime files (`.env.runtime`, `data/db.sqlite`, `data/uploads/`) were staged or modified.

### 2026-06-21T03:49:33Z - Task 4 (Pre-deployment Runtime Backup)
- **Backup Directory Path:** `/opt/gyu/backups/20260621T034933Z`
- **Stable Link Path:** `/opt/gyu/backups/trading-journal-predeploy-current`
- **SQLite Database Integrity:** `ok`
- **File Metadata (no secret content):**
  - `/opt/gyu/backups/20260621T034933Z/db.sqlite`: 339,968 bytes, mode=644, owner=gyu123:gyuedit
  - `/opt/gyu/backups/20260621T034933Z/.env.runtime`: 390 bytes, mode=600, owner=gyu123:gyuedit
  - `/opt/gyu/backups/20260621T034933Z/uploads`: directory, mode=2775, owner=gyu123:gyuedit
  - `/opt/gyu/backups/20260621T034933Z/trading-journal.service`: 353 bytes, mode=600, owner=gyu123:gyuedit
- **Note:** No hashes of secrets, environment variable values, or database row contents were captured or recorded.

### 2026-06-21T03:56:53Z - Task 5 (Web Service Migration)
- **Service Name:** `trading-journal.service`
- **Status:** enabled & active (running)
- **Process Working Directory:** `/opt/gyu/trading_journal` (verified via service environment/command)
- **Executable Path:** `/opt/gyu/trading_journal/.venv/bin/uvicorn`
- **Local HTTP Status Check:** `/access` returned HTTP 200
- **Rollback Backup Link:** `/opt/gyu/backups/trading-journal-predeploy-current`
- **Tests Execution:** PASS (35 tests run, 0 failures, 0 errors under virtualenv before service migration)
