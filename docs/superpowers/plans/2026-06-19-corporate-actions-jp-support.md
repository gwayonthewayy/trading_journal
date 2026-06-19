# Corporate Actions and Japan Market Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct Komico's bonus issue and add complete JP/JPY support to imports, quotes, UI, and valuation.

**Architecture:** Add a corporate-action event and service that adjusts one lot while preserving total cost. Extend the existing generic market/currency paths with JP/JPY and `.T` Yahoo symbols, then replay the June source files from the pre-import backup with an explicit Komico action manifest.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, SQLite, Jinja2, unittest, Yahoo chart API.

---

### Task 1: Corporate Action Domain Service

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Modify: `app/services.py`
- Test: `tests/test_corporate_actions.py`

- [ ] **Step 1: Write failing service tests**

```python
def test_bonus_issue_preserves_total_cost(self):
    result = create_bonus_issue(session, BonusIssueRequest(lot_id=1, additional_qty=52, ts=...))
    self.assertEqual(result["new_qty"], 104)
    self.assertEqual(result["new_entry_price"], 72150)

def test_bonus_issue_source_tag_is_idempotent(self):
    create_bonus_issue(session, request)
    result = create_bonus_issue(session, request)
    self.assertTrue(result["duplicate"])
```

- [ ] **Step 2: Verify tests fail because the event and service do not exist**

Run: `.venv\Scripts\python.exe -m unittest tests.test_corporate_actions -v`

- [ ] **Step 3: Add the event and service**

```python
class EventType(str, Enum):
    CORPORATE_ACTION = "CORPORATE_ACTION"

class BonusIssueRequest(SQLModel):
    lot_id: int
    additional_qty: float
    ts: datetime
    source_tag: str
    note: str | None = None
```

`create_bonus_issue` validates the lot and timestamp, calculates total lot quantity from original BUY quantity plus prior action quantities, preserves total cost, updates `qty_open` and `entry_price`, and records `reason=BONUS_ISSUE`.

- [ ] **Step 4: Run the focused and full tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_corporate_actions -v`

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/schemas.py app/services.py tests/test_corporate_actions.py
git commit -m "feat: add auditable bonus issue adjustments"
```

### Task 2: Japan Market Support

**Files:**
- Modify: `app/services.py`
- Modify: `app/templates/journal.html`
- Modify: `app/templates/stats.html`
- Modify: `scripts/import_miraeasset_overseas_xlsx.py`
- Modify: `docs/IMPORT_MIRAEASSET_OVERSEAS.md`
- Test: `tests/test_japan_market.py`
- Test: `tests/test_miraeasset_importers.py`

- [ ] **Step 1: Write failing JP mapping tests**

```python
def test_jpy_maps_to_japan(self):
    self.assertEqual(_market_currency_from_source_currency("JPY"), ("JP", "JPY"))

def test_japan_quote_symbol_uses_t_suffix(self):
    self.assertEqual(_quote_symbol_candidates("4004", "JP"), ["4004.T"])

def test_yen_symbol(self):
    self.assertEqual(_currency_symbol("JPY"), "¥")
```

- [ ] **Step 2: Verify the tests fail with missing JP behavior**

Run: `.venv\Scripts\python.exe -m unittest tests.test_japan_market -v`

- [ ] **Step 3: Implement JP/JPY support**

Map JPY to `JP/JPY`, normalize stored ticker to the broker code, produce `.T` quote candidates, add `¥`, and add JP/JPY options to buy, cashflow, edit, and filter controls. Preserve the imported broker name when Yahoo name lookup is unavailable.

- [ ] **Step 4: Verify tests and compile templates through app startup**

Run: `.venv\Scripts\python.exe -m unittest tests.test_japan_market tests.test_miraeasset_importers -v`

- [ ] **Step 5: Commit**

```bash
git add app/services.py app/templates/journal.html app/templates/stats.html scripts/import_miraeasset_overseas_xlsx.py docs/IMPORT_MIRAEASSET_OVERSEAS.md tests/test_japan_market.py tests/test_miraeasset_importers.py
git commit -m "feat: add Japan equity and JPY support"
```

### Task 3: Explicit Corporate Action Import Manifest

**Files:**
- Create: `data/import_manifests/miraeasset_corporate_actions.example.json`
- Modify: `scripts/import_miraeasset_kr_xlsx.py`
- Test: `tests/test_miraeasset_importers.py`

- [ ] **Step 1: Write failing manifest scheduling tests**

```python
def test_manifest_action_is_inserted_before_same_day_sell(self):
    events = schedule_corporate_actions(plan.events, actions)
    self.assertEqual(events[index].source_tag, "komico_bonus_20260527")
    self.assertEqual(events[index + 1].ticker, "183300")
```

- [ ] **Step 2: Verify the test fails because manifest support is absent**

Run: `.venv\Scripts\python.exe -m unittest tests.test_miraeasset_importers -v`

- [ ] **Step 3: Add explicit manifest loading and application**

Add `--corporate-actions` and apply each action immediately before the first event at or after its effective timestamp. Resolve the target BUY by ticker, source row, and purchase timestamp; never infer an action from a sell shortfall.

- [ ] **Step 4: Verify importer tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_miraeasset_importers -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/import_miraeasset_kr_xlsx.py data/import_manifests/miraeasset_corporate_actions.example.json tests/test_miraeasset_importers.py
git commit -m "feat: replay explicit corporate actions during imports"
```

### Task 4: Safe Database Replay and Verification

**Files:**
- Runtime only: `data/db.sqlite`
- Backup only: `data/backups/*.sqlite`

- [ ] **Step 1: Stop the local server and create a fresh SQLite backup**

Use SQLite's backup API, not a raw copy of an active database.

- [ ] **Step 2: Replay in a simulation database**

Restore `pre_miraeasset_import_20260619_165506.sqlite`, import domestic trades with the Komico manifest, import all overseas USD/HKD/JPY trades, and import the eight external cash flows.

- [ ] **Step 3: Verify simulation invariants**

```text
Komico open quantity = 0
Komico corporate actions = 1
4004 JP/JPY open quantity = 100
Second replay creates 0 events
PRAGMA integrity_check = ok
```

- [ ] **Step 4: Replace the real database only after simulation passes**

Repeat the verified replay against the real database or atomically replace it with the verified simulation database while the server is stopped.

- [ ] **Step 5: Restart and verify HTTP/UI**

Check `/access`, `/journal`, and `/portfolio`; confirm Komico is absent from open positions and the Japanese position is visible.

- [ ] **Step 6: Run all tests and commit no runtime data**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

