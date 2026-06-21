# Phase A Responsive UX/UI Detailed Implementation Plan

> [!IMPORTANT]
> **No functional UI changes or operational code changes** are implemented in this step. This file serves strictly as the executable blueprint (Step A0) to guide subsequent development iterations.
> **Verification Boundary:** Automated browser tests (Playwright) are currently unavailable in the environment. All visual layouts, touch targets, and mobile viewport tests are designated under `USER MANUAL CHECK` or `ANTI IDE REQUIRED`.

## Goal
Implement a responsive user interface foundation that adapts seamlessly to mobile devices (<= 768px) and desktop environments, without altering backend logic or introducing third-party UI/toast libraries. The mobile view will prioritize bottom navigation, drawer-based interactions, and simplified data presentations while retaining the current powerful data grid for PC users.

## Architecture
- **Responsive Layout Strategy:** Use CSS Variables and Media Queries (`max-width: 768px`) for layout switching.
- **Mobile Navigation:** Bottom fixed navigation (`<nav class="bottom-nav">`) replacing the top header links.
- **Drawers/Sheets:** Use existing CSS-based drawer mechanics (`.drawer`) for filters, menus, and edits instead of modals.
- **Components:** Maintain a singleton-canvas approach for ApexCharts to prevent rendering duplication.
- **State Management:** Use existing minimal JS and Jinja2 templates without relying on heavy frontend frameworks.

## Tech Stack
- **Frontend:** HTML5, CSS3 (Vanilla, CSS Variables), Vanilla JavaScript
- **Backend:** FastAPI, Jinja2
- **Testing:** `unittest` with in-memory SQLite (`sqlite://`), manual browser validation

---

## 1. Safety and Isolation Boundaries
- Do **NOT** modify, stage, or commit `.env.runtime`.
- Do **NOT** read or parse secrets from `.env.runtime`.
- Do **NOT** modify `data/db.sqlite` or `data/uploads/`.
- All tests must use `sqlite://` via `StaticPool` and override `get_session` via `app.dependency_overrides`.

---

## Step A1: Responsive App Shell

### Objectives
- Unified responsive navigation layout (768px threshold).
- Header height capped at `64px` max.
- Bottom navigation bar: `매매일지`, `포트폴리오`, `분석`.
- User Menu Drawer: `ADMIN`/`VIEWER` role pill. Hidden `username` DOM slot. No placeholder/non-functional UI.
- Use Korean terms for periods and menus.
- Ensure `safe-area-inset` is covered in CSS tests.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_app_shell.py` with failing assertions.
- [ ] Update `app/static/style.css`: Add `@media (max-width: 768px)`, define `height: 64px` for header.
- [ ] Update `app/static/style.css`: Add `.bottom-nav` styles including `padding-bottom: env(safe-area-inset-bottom)`.
- [ ] Update `app/templates/base.html`: Move PC navigation to a conditional or responsive hidden block.
- [ ] Update `app/templates/base.html`: Add `<nav class="bottom-nav">` with items (매매일지, 포트폴리오, 분석).
- [ ] Update `app/templates/base.html`: Add `#user-menu-drawer`.
- [ ] Update `app/templates/base.html`: Add `ADMIN`/`VIEWER` role pill and hidden `username` slot in `#user-menu-drawer`.
- [ ] Run test and ensure it passes.
- [ ] `USER MANUAL CHECK`: Open on mobile (viewport <= 768px) and verify.

### TDD & Minimum Implementation
**Test File:** `tests/test_app_shell.py`
```python
import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestAppShell(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_mobile_elements_exist(self):
        response = self.client.get("/")
        html = response.text
        self.assertIn('class="bottom-nav"', html)
        self.assertIn('매매일지', html)
        self.assertIn('id="user-menu-drawer"', html)
        self.assertIn('style="display: none;" id="username-slot"', html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_app_shell`
**Expected Failure:** `AssertionError: 'class="bottom-nav"' not found in html`
**Min Impl:**
```html
<nav class="bottom-nav">
  <a href="/journal">매매일지</a>
  <a href="/portfolio">포트폴리오</a>
  <a href="/stats">분석</a>
</nav>
<div id="user-menu-drawer" class="drawer">
  <span class="role-pill">{{ user_role }}</span>
  <span id="username-slot" style="display: none;"></span>
</div>
```

### Stop & Commit Point
- **Commit Message:** `feat(ui): implement responsive app shell (<=768px) with bottom nav and user menu`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A2**

---

## Step A2: Journal Workflow

### Objectives
- Maintain spreadsheet layout on PC.
- Mobile View: Suppress `#journal-table`, show `journal-mobile-card` list.
- Implement drawers for Filters, Pagination, Edit, Delete on mobile vs desktop.
- Floating Quick Record FAB for new entries.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_journal_ui.py` with assertions for mobile cards, filter drawer, pagination drawer, edit drawer, delete drawer.
- [ ] Update `app/static/style.css`: Add display toggles for `#journal-table` and `.journal-mobile-card` based on `768px` media query.
- [ ] Update `app/templates/journal.html`: Implement `#filter-drawer`, `#pagination-drawer`, `#edit-drawer`, `#delete-drawer`.
- [ ] Update `app/templates/journal.html`: Add loop to render `.journal-mobile-card` items.
- [ ] Update `app/templates/journal.html`: Add `.fab-quick-record` button.
- [ ] Run test and ensure it passes.
- [ ] `USER MANUAL CHECK`: Verify cards layout, FAB interaction, and drawers (Filter, Pagination, Edit, Delete).

### TDD & Minimum Implementation
**Test File:** `tests/test_journal_ui.py`
```python
import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestJournalUI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_journal_mobile_elements(self):
        response = self.client.get("/journal")
        html = response.text
        self.assertIn('class="journal-mobile-card"', html)
        self.assertIn('id="filter-drawer"', html)
        self.assertIn('id="pagination-drawer"', html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_journal_ui`
**Expected Failure:** `AssertionError: 'class="journal-mobile-card"' not found in html`
**Min Impl:**
```html
<div class="journal-mobile-card">...</div>
<div id="filter-drawer" class="drawer">...</div>
```

### Stop & Commit Point
- **Commit Message:** `feat(ui): add mobile trade cards, drawers for filter/pagination/edit/delete, and FAB`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A3**

---

## Step A3: Analytics Simplification

### Objectives
- Simplify metrics terminology (`기간 수익률`, `확정 수익률`, hide M1 in `고급 지표`).
- Merge 4 separate daily/weekly/monthly/yearly charts into `#stats-primary-chart`.
- Add switcher: `Daily | Weekly | Monthly | Yearly`.
- Integrate Monthly Check view as a secondary tab.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_stats_ui.py` asserting `#stats-primary-chart` and new translated labels.
- [ ] Update `app/templates/stats.html`: Rename M2 to `기간 수익률`, Realized Return to `확정 수익률`.
- [ ] Update `app/templates/stats.html`: Wrap M1 in an accordion `<details class="고급-지표">`.
- [ ] Update `app/templates/stats.html`: Replace multiple charts with `#stats-primary-chart` and a switcher group.
- [ ] Update `app/templates/stats.html`: Integrate Monthly Check content.
- [ ] Update `app/static/style.css`: Add styles for switcher and tabs.
- [ ] Run test and ensure it passes.
- [ ] `USER MANUAL CHECK`: Toggle switcher options and ensure only one ApexCharts instance renders.

### TDD & Minimum Implementation
**Test File:** `tests/test_stats_ui.py`
```python
import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestStatsUI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_stats_elements(self):
        response = self.client.get("/stats")
        html = response.text
        self.assertIn('기간 수익률', html)
        self.assertIn('확정 수익률', html)
        self.assertIn('id="stats-primary-chart"', html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_stats_ui`
**Expected Failure:** `AssertionError: '기간 수익률' not found`
**Min Impl:**
```html
<div>기간 수익률</div>
<div id="stats-primary-chart"></div>
```

### Stop & Commit Point
- **Commit Message:** `feat(ui): simplify stats metrics and consolidate charts into a single canvas`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A4**

---

## Step A4: Portfolio Simplification

### Objectives
- Mobile View: Compact Ticker Cards showing open value, cost, unrealized PnL, open risk.
- Lots details in an accordion list inside the card.
- Refresh workflow loading states.

### Implementation Checklist (2~5 minute tasks)
- [ ] Create `tests/test_portfolio_ui.py` asserting `.portfolio-ticker-card` and loading state elements.
- [ ] Update `app/templates/portfolio.html`: Add `.portfolio-ticker-card` container.
- [ ] Update `app/templates/portfolio.html`: Add collapsible `<details>` for lots.
- [ ] Update `app/templates/portfolio.html`: Add loading indicator elements (spinner/stretching).
- [ ] Update `app/static/style.css`: Add `.portfolio-ticker-card` styles.
- [ ] Run test and ensure it passes.
- [ ] `USER MANUAL CHECK`: Verify portfolio cards collapse correctly and check refresh loading indicators.

### TDD & Minimum Implementation
**Test File:** `tests/test_portfolio_ui.py`
```python
import unittest
from fastapi.testclient import TestClient
from app.main import app

class TestPortfolioUI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_portfolio_elements(self):
        response = self.client.get("/portfolio")
        html = response.text
        self.assertIn('class="portfolio-ticker-card"', html)
```
**Run Command:** `.venv/bin/python -m unittest tests.test_portfolio_ui`
**Expected Failure:** `AssertionError: 'class="portfolio-ticker-card"' not found`
**Min Impl:**
```html
<div class="portfolio-ticker-card">
  <details><summary>Lots</summary>...</details>
</div>
```

### Stop & Commit Point
- **Commit Message:** `feat(ui): implement mobile portfolio ticker cards and refresh indicators`
- **Wait for User Approval:** 🔴 **STOP HERE AND ASK USER TO PROCEED TO A5**

---

## Step A5: Verification & Production Release

### Objectives
- Complete regression suite (excluding `test_japan_market.py`).
- No git dirtiness or leaked `.env.runtime`.
- Visual cross-device testing.

### Commands to Run
```bash
mapfile -t test_modules < <(find tests -maxdepth 1 -type f -name 'test_*.py' ! -name 'test_japan_market.py' -printf '%f\n' | sed -e 's/\.py$//' -e 's#^#tests.#' | sort)
.venv/bin/python -m unittest -v "${test_modules[@]}"

git status --short
git diff --cached --name-only
```

### Stop & Commit Point
- **Commit Message:** `chore(release): complete Phase A verification`
- **Wait for User Approval:** 🔴 **STOP HERE**
