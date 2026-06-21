# Production Rollout Log — 2026-06-21

## Safety boundary

- Runtime secrets and data remain outside Git.
- `.env.runtime`, `data/db.sqlite`, and `data/uploads/` are not modified by documentation or Git tasks.
- `tests/test_japan_market.py` is not modified or executed by this rollout.
- Database restoration requires explicit human approval.

## Agent handoff

- Design commit: `54e52e1`
- Current owner: Gemini (Task 2 completed, handing back to Codex)
- Execution model: sequential Codex/Gemini handoffs; never concurrent edits

## Phase status

- Git integration: planned
- Runtime backup: planned
- Friend-server service migration: planned
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
