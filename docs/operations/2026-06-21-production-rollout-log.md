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
- Local browser acceptance: complete
- External acceptance: complete
- Reboot recovery: deferred (pending)

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

### 2026-06-21T04:15:00Z - Security Remediation (Secrets Rotation)
- **Actions Performed:**
  - Rotated `TJ_SIGNING_SECRET` with a new cryptographically secure random 32-byte hex secret.
  - Rotated `TJ_VIEWER_TOKEN` and `TJ_ADMIN_TOKEN` with new cryptographically secure random url-safe base64 tokens.
  - Incremented `TJ_AUTH_VERSION` to invalidate all active and previous session cookies.
  - Rotated `TJ_ADMIN_PASSWORD_HASH` using Argon2id via virtualenv python.
  - Restarted `trading-journal.service` successfully (status: active).
  - Verified local HTTP response for `/access` returned HTTP 200.
  - Verified previous sessions are invalidated due to the incremented `auth_version`.
- **Note:** All actual rotated secrets, tokens, password hashes, and database values are excluded from logs, terminal history, and chat.

### 2026-06-21T05:52:00Z - Database and Uploads Restoration
- **Actions Performed:**
  - Identified that the database backed up in Task 4 (`/opt/gyu/backups/20260621T034933Z/db.sqlite`) was a stale version from March 6th, 2026.
  - Verified and compared database candidates: Active DB, Task 4 backup, soso6079 original DB, and ZIP staging DB.
  - Identified the staging bundle `/opt/gyu/staging/runtime_bundle_latest.zip` as containing the most recent database (`db.sqlite` with events up to 2026-06-19 and 1,181 events).
  - Prepared and staged a secure, verified folder structure (`data.new`) with whitelisted files only, preserving UID/GID and permission metadata.
  - Stopped the `trading-journal.service` (confirmed state: inactive) and verified no active file locks.
  - Atomically swapped `/opt/gyu/trading_journal/data` to a timestamped backup directory `/opt/gyu/backups/data_backup__8ygibuw`.
  - Atomically deployed the verified staging candidate to `/opt/gyu/trading_journal/data/`.
  - Re-verified database integrity (`ok`), total events (`1,181`), latest event timestamp (`2026-06-19`), and DB SHA-256 hash.
  - Verified uploads directory matched the staged manifest (25 items).
  - Retained `.env.runtime` unmodified.
- **Note:** All actual secrets, tokens, and database values are excluded from logs, terminal history, and chat.

### 2026-06-21T06:26:00Z - Task 6 (Local Browser Acceptance / Human-Assisted Verification)
- **Verification Method:** Human-Assisted Verification (Explicitly marked as non-automatic)
- **Outcome:** PASS
- **Verified Areas:**
  - `/journal` page renders successfully with latest event data.
  - `/portfolio` page renders successfully.
  - `/stats` page renders successfully.
  - Total event count verified: 1,181 events.
  - Latest transaction data (up to 2026-06-19) and associated uploaded chart images display correctly.
  - 8 ApexCharts canvas containers verified (Count is exactly 1 initially, and remains exactly 1 after first and second theme toggles).
  - Chart theme colors adjust normally on theme toggling.
  - New browser console errors detected: 0.
  - Active configuration files (`.env.runtime`) and security credentials are unchanged.
- **Note:** All actual secrets, tokens, password hashes, and database values are excluded from logs, terminal history, and chat.

### 2026-06-21T08:05:00Z - Task 7 (Cloudflared Service Installation and Verification)
- **New Service:** `cloudflared.service` (configured under user `gyu123` and group `gyuedit`, pointing to `/usr/bin/cloudflared` binary and `/etc/cloudflared/config.yml` configuration)
- **Legacy Service:** `cloudflared-trading-journal.service` (running unaffected under user `soso6079` pointing to `/opt/bin/cloudflared` binary)
- **Status Checks:**
  - `cloudflared-trading-journal.service`: active & enabled
  - `cloudflared.service`: active & enabled
  - `trading-journal.service`: active & enabled
- **Tunnel Connectivity:**
  - New `trading-journal` tunnel (`263386ee-cdcc-4b4c-9a57-dc04e0bae4fb`): Connected (2 active connections)
- **DNS and HTTP Verification:**
  - `https://tjgyu.site/access` returned HTTP 200 with correct page contents
  - Port 8000 bound strictly to `127.0.0.1:8000` (not exposed globally)
- **Legacy Domains Routing Verification:**
  - `trading-journal.work/access`: HTTP 200
  - `reports.trading-journal.work`: HTTP 200
  - `terminal.trading-journal.work`: HTTP 307
  - `betawavve.xyz`: HTTP 303
- **Note:** No credential file JSON paths, private keys, or actual tokens are logged.

### 2026-06-21T08:26:00Z - Task 8 (External Browser Acceptance / Human-Assisted Verification)
- **Verification Method:** Human-Assisted Verification (Explicitly marked as non-automatic)
- **Outcome:** PASS
- **Verified Areas:**
  - `https://tjgyu.site/access` and Admin login: PASS
  - `/journal`, `/portfolio`, and `/stats` pages: PASS (rendered successfully)
  - Latest transaction data (up to 2026-06-19) and associated uploaded chart images: PASS (displayed normally)
  - 8 ApexCharts canvas containers: Count is exactly 1 initially and remains exactly 1 after 2 theme transitions (no duplication).
  - Theme-specific chart colors: Correctly adjusted on theme toggling.
  - Browser console errors: 0 new errors detected.
  - Data integrity safety:
    - Opening and canceling the trade edit modal: PASS (no data changed).
    - Opening and canceling the image upload modal: PASS (no data changed).
  - UX Feedback: Modal UX has minor usability/convenience issues, but they do not block deployment. Tracked for future improvements.
- **Note:** All actual secrets, tokens, password hashes, and database transaction values are excluded from logs.

### 2026-06-21T09:45:00Z - UI/UX Edit Drawer Modernization (Superpowers Spec Implementation)
- **Actions Performed**:
  - Replaced the legacy `window.prompt` JSON-string payload editor in `journal.html` with a structured slide-out drawer (`#drawer-edit`).
  - Added form validation and type-specific input visibility (e.g. BUY shows Qty, Price, Fees, SL, TP; SELL shows Price, Fees; CASHFLOW shows Cash Amount; REVIEW shows Review Text).
- **Verification Method**: Browser Subagent Automated Verification (Local Port 8002)
- **Outcome**: PASS
- **Verified Areas**:
  - Administrative login via `/access/admin/...` with password: PASS
  - Triggering Edit on a transaction row slides open the `#drawer-edit` drawer: PASS
  - The drawer is correctly pre-populated with current values: PASS
  - Modifying the 'Note' field in the drawer and clicking 'Save Changes' correctly fires a `PATCH` request, reloads the journal ledger table, and displays the updated value ('Verified by Browser Subagent'): PASS
  - The drawer closes automatically on success: PASS
  - No new JavaScript errors in the browser console: PASS
- **Note:** All actual secrets, tokens, password hashes, and database transaction values are excluded from logs.


## Current Deployment Status

- **Web Service Status**: `trading-journal.service` is active and enabled, running from `/opt/gyu/trading_journal`.
- **New Tunnel Status**: `cloudflared.service` is active and enabled, routing `https://tjgyu.site` to the local backend.
- **Operational URL**: `https://tjgyu.site` is normally operating and publicly accessible.
- **Validation Status**: Task 6 (Local), Task 8 (External) Human-Assisted verifications, and UI/UX Edit Drawer Browser Subagent verifications are all PASS.
- **Data Status**: SQLite database and uploads directory successfully restored from `runtime_bundle_latest.zip`.
- **Legacy Service Boundary**: The pre-existing `cloudflared-trading-journal.service` has been left running and unaffected, as it is required to route other active websites (`trading-journal.work`, `reports`, `terminal`, `betawavve`).
- **Pending Tasks**:
  - Reboot recovery validation: **Deferred** (pending scheduled server maintenance to avoid disrupting active user sessions and agent processes).
  - KIS activation: **Separate step** (not enabled under current scope).




