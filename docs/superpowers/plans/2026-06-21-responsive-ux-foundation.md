# Phase A Responsive UX/UI Detailed Implementation Plan

> [!IMPORTANT]
> **No functional UI changes or operational code changes** are implemented in this step. This file serves strictly as the executable blueprint (Step A0) to guide subsequent development iterations.
> **Verification Boundary:** Automated browser tests (Playwright) are currently unavailable in the environment. All visual layouts, touch targets, and mobile viewport tests are designated under `USER MANUAL CHECK` or `ANTI IDE REQUIRED`. The Antigravity CLI does not and will not claim to have executed browser verifications.

## Goal
Implement a responsive user interface foundation that adapts seamlessly to mobile devices (<= 768px) and desktop environments, without altering backend logic or introducing third-party UI/toast libraries. The mobile view will prioritize bottom navigation, drawer-based interactions, and simplified data presentations while retaining the current powerful data grid for PC users.

## Architecture
- **Responsive Layout Strategy:** Use CSS Variables and Media Queries (`max-width: 768px`) for layout switching.
- **Mobile Navigation:** Bottom fixed navigation (`<nav class="bottom-nav">`) replacing the top header links.
- **Drawers/Sheets:** Use existing CSS-based drawer mechanics (`.drawer`) for filters, menus, and edits instead of modals.
- **Components:** Maintain a singleton-canvas approach for ApexCharts to prevent rendering duplication.
- **State Management:** Single Data Flow. Mobile views (like cards) will be generated client-side from the primary DOM elements (like table rows) to prevent duplicate template logic and maintain sync with existing JS update cycles.
- **Testing Strategy:** 
  - Do not use naive `TestClient(app)` requests that might load production `.env.runtime` configurations inadvertently.
  - Rely on static source code inspection patterns (similar to `tests/test_stats_and_theme_templates.py`) to verify template structural changes securely.
  - Only initialize isolated dependency overrides (`get_session`) if full integration tests are explicitly required.

## Tech Stack
- **Frontend:** HTML5, CSS3 (Vanilla, CSS Variables), Vanilla JavaScript
- **Backend:** FastAPI, Jinja2
- **Testing:** Python `unittest`, static source inspection, manual browser validation

---

## 1. Safety and Isolation Boundaries
- Do **NOT** modify, stage, or commit `.env.runtime`.
- Do **NOT** read or parse secrets from `.env.runtime`.
- Do **NOT** modify `data/db.sqlite` or `data/uploads/`.
- All integration tests must use `sqlite://` via `StaticPool` and override `get_session` via `app.dependency_overrides`.

---

## Step A1: Responsive App Shell

### Objectives
- Unified responsive navigation layout (768px threshold).
- Header height capped at `64px` max.
- Bottom navigation bar: `매매일지`, `포트폴리오`, `분석`.
- User Menu Drawer:
  - Triggered by header button.
  - Contains `{{ auth_role }}` role pill and a hidden `<span id="username-slot" hidden></span>`.
  - Accessible interaction: open/close handling, `aria-expanded` toggling, overlay background click-to-close, `Escape` key to close, and focus return.
- Ensure the existing PC menu layout remains intact on desktop viewports.
- Ensure the `/access` (unauthorized) page does not break or expose broken authenticated UI elements.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_app_shell_source.py` with static file inspections for `.bottom-nav` and `#user-menu-drawer`.
- [ ] Update `app/static/style.css`: Add `@media (max-width: 768px)`, define `height: 64px` for header.
- [ ] Update `app/static/style.css`: Add `.bottom-nav` styles including `padding-bottom: env(safe-area-inset-bottom)`.
- [ ] Update `app/templates/base.html`: Move PC navigation to a responsive hidden block.
- [ ] Update `app/templates/base.html`: Add `<nav class="bottom-nav">` with items (매매일지, 포트폴리오, 분석).
- [ ] Update `app/templates/base.html`: Add `#user-menu-drawer` with `<span class="role-pill">{{ auth_role }}</span>` and `<span id="username-slot" hidden></span>`.
- [ ] Update `app/templates/base.html` JS: Add User Menu open/close functions handling `aria-expanded`, overlay, and `Escape` key listeners.
- [ ] Run test and ensure it passes.

### TDD & Complete Implementation Example
**Test File:** `tests/test_app_shell_source.py`
```python
import unittest
from pathlib import Path

class TestAppShellSource(unittest.TestCase):
    def setUp(self):
        self.base_html = Path("app/templates/base.html").read_text(encoding="utf-8")

    def test_mobile_elements_exist_in_template(self):
        self.assertIn('class="bottom-nav"', self.base_html)
        self.assertIn('매매일지', self.base_html)
        self.assertIn('id="user-menu-drawer"', self.base_html)
        self.assertIn('{{ auth_role }}', self.base_html)
        self.assertIn('id="username-slot"', self.base_html)
        self.assertIn('hidden', self.base_html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_app_shell_source`
**Expected Failure:** `AssertionError: 'class="bottom-nav"' not found in base_html`

### Stop & Commit Point
- **Commit Message:** `feat(ui): implement responsive app shell (<=768px) with bottom nav and user menu`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A2**

---

## Step A2: Journal Workflow (Single Data Flow)

### Objectives
- Maintain spreadsheet layout on PC.
- Mobile View: Display `div.journal-mobile-card` items dynamically generated from the table.
- **Strict Single Data Flow:** Do NOT use a Jinja loop to pre-render mobile cards. The client-side function `renderMobileCardsFromJournalRows()` must read the `tr.journal-row` elements (generated by Jinja or updated by `loadJournalPage()`), extract dataset/cell values, and generate the mobile cards.
- Call `renderMobileCardsFromJournalRows()` after every state change: initial load, filter application, reset, pagination, edits, and deletions.
- Existing actions (Edit, Attach, Delete) inside mobile cards must directly bind to and reuse the existing `handleActionClick()` function logic. No duplicated event handlers.
- Use the existing `#drawer-edit` ID for edits. Do not create `#edit-drawer`.
- Remove any plans for separate Pagination or Delete drawers; use the existing inline pagination and browser-native/existing delete confirmations.
- Add `.fab-quick-record` floating action button for mobile.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_journal_source.py` verifying the presence of JS function `renderMobileCardsFromJournalRows` and `#drawer-edit` preservation.
- [ ] Update `app/static/style.css`: Toggle visibility between `#journal-table` and a new `#mobile-cards-container` based on `768px` media query.
- [ ] Update `app/templates/journal.html`: Add `<div id="mobile-cards-container"></div>` and the `.fab-quick-record` button.
- [ ] Update `app/templates/journal.html` JS: Implement `renderMobileCardsFromJournalRows()` to map `tr.journal-row` to card HTML and append to container.
- [ ] Update `app/templates/journal.html` JS: Append `renderMobileCardsFromJournalRows()` to the end of `loadJournalPage()` and DOMContentLoaded.
- [ ] Update `app/templates/journal.html` JS: Ensure card buttons emit events that hook into `handleActionClick()`.
- [ ] Run test and ensure it passes.

### TDD & Complete Implementation Example
**Test File:** `tests/test_journal_source.py`
```python
import unittest
from pathlib import Path

class TestJournalSource(unittest.TestCase):
    def setUp(self):
        self.journal_html = Path("app/templates/journal.html").read_text(encoding="utf-8")

    def test_mobile_cards_data_flow_logic(self):
        self.assertIn('function renderMobileCardsFromJournalRows()', self.journal_html)
        self.assertIn('id="drawer-edit"', self.journal_html)
        self.assertNotIn('id="edit-drawer"', self.journal_html)
        self.assertIn('class="fab-quick-record"', self.journal_html)
        self.assertIn('handleActionClick(', self.journal_html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_journal_source`
**Expected Failure:** `AssertionError: 'function renderMobileCardsFromJournalRows()' not found in journal_html`

### Stop & Commit Point
- **Commit Message:** `feat(ui): implement single-data-flow mobile trade cards and Quick Record FAB`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A3**

---

## Step A3: Analytics Simplification

### Objectives
- Simplify metrics: Rename `M2` to `기간 수익률`, and `Realized Return` to `확정 수익률`.
- Hide `M1` inside a `<details class="고급-지표">` accordion.
- Merge the 4 separate **Return (수익률)** charts (Daily, Weekly, Monthly, Yearly) into a single unified canvas `#stats-primary-chart`.
- Keep the 4 **FX & Distribution** charts exactly as they are.
- Add a switcher control for the unified return chart with exact text: `일간 / 주간 / 월간 / 연간`.
- Chart Update Lifecycle: Ensure JS properly calls `chart.destroy()` before creating a new ApexCharts instance on the single canvas when switching timeframes.
- Move Monthly Check page: Remove from `base.html` main menu. Update `main.py` so `/monthly-check` redirects to `/stats?tab=monthly-check`.
- In `stats.html`, parse the URL parameter `tab=monthly-check` via JS and toggle visibility between the Stats dashboard and an embedded Monthly Check container.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_stats_source.py` to assert the single canvas, exact switcher text, metric names, and chart destroy logic.
- [ ] Update `main.py`: Redirect `/monthly-check` endpoint to `RedirectResponse(url="/stats?tab=monthly-check")`.
- [ ] Update `base.html`: Remove the standalone `/monthly-check` navigation link.
- [ ] Update `app/templates/stats.html`: Rename metrics (`기간 수익률`, `확정 수익률`) and wrap M1 in `<details>`.
- [ ] Update `app/templates/stats.html`: Replace the 4 return chart containers with `<div id="stats-primary-chart"></div>` and add the `일간 / 주간 / 월간 / 연간` switcher buttons.
- [ ] Update `app/templates/stats.html` JS: Implement switcher logic with `if (primaryChart) primaryChart.destroy(); primaryChart = new ApexCharts(...)`.
- [ ] Update `app/templates/stats.html` JS: Add logic to parse `?tab=monthly-check` and show/hide the embedded monthly check view.
- [ ] Run test and ensure it passes.

### TDD & Complete Implementation Example
**Test File:** `tests/test_stats_source.py`
```python
import unittest
from pathlib import Path

class TestStatsSource(unittest.TestCase):
    def setUp(self):
        self.stats_html = Path("app/templates/stats.html").read_text(encoding="utf-8")
        self.main_py = Path("app/main.py").read_text(encoding="utf-8")

    def test_stats_metrics_and_unified_chart(self):
        self.assertIn('기간 수익률', self.stats_html)
        self.assertIn('확정 수익률', self.stats_html)
        self.assertIn('id="stats-primary-chart"', self.stats_html)
        self.assertIn('일간 / 주간 / 월간 / 연간', self.stats_html)
        self.assertIn('.destroy()', self.stats_html)

    def test_monthly_check_redirect(self):
        self.assertIn('RedirectResponse(url="/stats?tab=monthly-check")', self.main_py)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_stats_source`
**Expected Failure:** `AssertionError: '기간 수익률' not found in stats_html`

### Stop & Commit Point
- **Commit Message:** `feat(ui): unify return charts, simplify metrics, and embed monthly check`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A4**

---

## Step A4: Portfolio Simplification

### Objectives
- Mobile View: Implement compact `.portfolio-ticker-card` elements for mobile view.
- Display open value, cost, unrealized PnL, and open risk at a glance.
- Wrap lot details in a responsive `<details>` accordion list.
- Use the existing `#portfolio-market-status` container for all API refresh status updates. Do NOT introduce new toast UI elements.
- Implement explicit DOM classes/content updates on `#portfolio-market-status` for states:
  - Empty: default text
  - Loading: `"데이터 갱신 중..."`
  - Success: `"업데이트 완료"`
  - Stale: `"데이터 지연"`
  - Error: `"업데이트 실패"`

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_portfolio_source.py` asserting `#portfolio-market-status` update logic and `.portfolio-ticker-card`.
- [ ] Update `app/templates/portfolio.html`: Add `.portfolio-ticker-card` and `<details>` structure inside the portfolio list generation block.
- [ ] Update `app/templates/portfolio.html` JS: Update the `refreshMarketData` function to manipulate `#portfolio-market-status.innerHTML` based on fetch states.
- [ ] Update `app/static/style.css`: Add styles for `.portfolio-ticker-card` to display as block only under 768px.
- [ ] Run test and ensure it passes.

### TDD & Complete Implementation Example
**Test File:** `tests/test_portfolio_source.py`
```python
import unittest
from pathlib import Path

class TestPortfolioSource(unittest.TestCase):
    def setUp(self):
        self.portfolio_html = Path("app/templates/portfolio.html").read_text(encoding="utf-8")

    def test_portfolio_status_and_cards(self):
        self.assertIn('class="portfolio-ticker-card"', self.portfolio_html)
        self.assertIn('document.getElementById(\'portfolio-market-status\')', self.portfolio_html)
        self.assertIn('데이터 갱신 중...', self.portfolio_html)
        self.assertIn('업데이트 완료', self.portfolio_html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_portfolio_source`
**Expected Failure:** `AssertionError: 'class="portfolio-ticker-card"' not found in portfolio_html`

### Stop & Commit Point
- **Commit Message:** `feat(ui): implement mobile portfolio ticker cards and market status indicators`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A5**

---

## Step A5: Verification & Production Release

### Objectives
- Prove that code is clean and passes all automated and manual checks before merging to `main`.
- Prevent accidental exposure of secrets or database files.
- The CLI AI MUST explicitly pause and wait for the human developer to approve merging and deployment.

### A5-1: Git and Environment Safety Check
1. Discover and execute safe test modules:
    ```bash
    mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
    .venv/bin/python -m unittest -v "${test_modules[@]}"
    ```
2. Verify git staged area and diff to ensure no `.env.runtime` or `data/*.sqlite` files are accidentally tracked:
    ```bash
    git status --short
    git diff --cached --name-only
    ```

### A5-2: User Manual Verification Matrix
Record the manual test results in the next response before requesting a merge.

| Viewport | Element Tested | Pass/Fail | Notes / Adjustments |
|---|---|---|---|
| 360px | Bottom Navigation sticky, safe-area-inset | | |
| 390px | User Menu Drawer open/close/escape | | |
| 768px | Journal Mobile Cards generation | | |
| 1440px | Journal PC layout preserved | | |
| All | Stats Return Chart Switcher | | |
| All | Unauthorized `/access` view | | |

### A5-3: Rollback / Fix Process
- If any test in A5-2 fails:
  - Do NOT proceed to merge.
  - Implement the specific fix in `feat/responsive-ux-foundation`.
  - Add a fix commit (e.g., `fix(ui): correct z-index on bottom nav`).
  - Repeat A5-2.

### A5-4: Final Merge and Restart
> [!CAUTION]
> **DO NOT** merge into `main` or restart the systemd service without explicit user approval.
> The CLI cannot perform Playwright checks; it must rely entirely on the human developer's confirmation of the Manual Verification Matrix.

**Once User Approves:**
```bash
git checkout main
git merge feat/responsive-ux-foundation
git push origin main
sudo systemctl restart trading-journal.service
```

### Stop & Commit Point
- **Commit Message:** `chore(release): complete Phase A verification and prepare for rollout`
- **Wait for User Approval:** 🔴 **STOP HERE**
