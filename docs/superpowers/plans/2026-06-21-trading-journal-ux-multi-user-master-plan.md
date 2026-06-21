# Trading Journal UX and Multi-User Portal Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement each approved phase. Use `superpowers:verification-before-completion` before every completion claim. Do not execute a later phase before its approval checkpoint.

**Goal:** Redesign the existing trading journal into a clean PC/mobile experience first, then add an invite-only multi-user account system with strict per-user data isolation.

**Architecture:** Phase A changes presentation and responsive interaction while preserving the current authentication and data model. Phase B is a separate security-sensitive project that replaces token-path access with account sessions and adds tenant ownership to every private resource.

**Tech Stack:** FastAPI, Jinja2, vanilla JavaScript, CSS, SQLModel, SQLite, Argon2, Playwright/Anti IDE browser testing, systemd, Cloudflare Tunnel.

---

## 1. Roles

### User

- Approves plans, visual direction, production deployment, and any `sudo` operation.
- Performs final checks in the personal browser where real authentication is required.
- Never sends passwords, raw tokens, hashes, or runtime secrets through chat.

### Gemini Anti IDE

- Reads and modifies the server repository in an isolated feature branch.
- Runs desktop/mobile browser tests and captures screenshots.
- Uses only a copied test database and test uploads for write-capable browser tests.
- Stops at every approval checkpoint and does not merge or deploy autonomously.

### Codex

- Reviews Gemini's plan, commits, diffs, security boundaries, and browser evidence.
- Checks for regressions, missing tenant filters, unsafe runtime changes, and inadequate tests.
- Does not need production credentials; reviews source and non-secret evidence through GitHub.

---

## 2. Non-Negotiable Safety Rules

- Never modify or commit `.env.runtime`, the operational `data/db.sqlite`, or `data/uploads/` during development tests.
- Browser tests that issue `POST`, `PATCH`, or `DELETE` must use an isolated DB, isolated uploads directory, and a separate port such as `8002`.
- Do not replace password hashes just to automate a browser login.
- Do not print tokens, invitation links, password hashes, cookies, or broker credentials.
- Do not work directly on `main`; use a feature branch and frequent commits.
- Do not touch `tests/test_japan_market.py`.
- Do not restart production services or run `sudo` without explicit user approval.
- Keep the existing reboot-validation task deferred.

---

# Phase A: Responsive UX/UI

## Step A0: Baseline and Detailed Plan

**Owner:** Gemini Anti IDE

**User sends Gemini:**

```text
/opt/gyu/trading_journal에서 Phase A UX/UI 작업을 준비해줘.

REQUIRED SKILLS:
- superpowers:brainstorming
- superpowers:writing-plans

아직 구현하지 마라. HANDOFF.md, handoff.md, 최근 git log, 롤아웃 로그,
app/templates/base.html, journal.html, portfolio.html, stats.html,
app/static/style.css를 먼저 읽어라.

현재 모바일 문제:
- 상단 topbar가 여러 줄로 감겨 화면 대부분을 차지한다.
- 메뉴, CSV, ADMIN, Logout, 테마 버튼이 모두 노출된다.
- 모바일 첫 화면에서 거래 내용이 충분히 보이지 않는다.

목표:
- 매매일지 / 포트폴리오 / 분석의 3개 핵심 구조
- PC 표 중심, 모바일 카드 중심
- 모바일 56~64px 상단 헤더와 하단 내비게이션
- 편집 드로어는 PC 측면 패널, 모바일 전체 화면
- M2를 기간 수익률로 표시하고 M1은 고급 영역으로 숨김
- Monthly Check는 분석 내부로 이동
- KIS Sync, CSV, 테마, 권한 표시, 로그아웃은 사용자 메뉴로 이동
- 현재 인증 역할을 표시할 재사용 가능한 사용자 메뉴 슬롯 준비

운영 파일과 운영 DB를 변경하지 말고,
docs/superpowers/plans/YYYY-MM-DD-responsive-ux-foundation.md에
파일별·테스트별·커밋별 상세 계획을 작성한 뒤 멈춰라.
```

**Deliverables:** Current desktop/mobile screenshots, UI inventory, exact implementation plan, no code changes.

**Approval checkpoint:** User sends the plan and screenshots to Codex for review.

## Step A1: Responsive App Shell

**Owner:** Gemini Anti IDE

**Files:** `app/templates/base.html`, `app/static/style.css`, relevant template tests.

- Desktop retains compact top navigation.
- Mobile header is at most 64px and shows only TJ mark, current page title, and user/settings trigger.
- Mobile primary navigation is fixed at the bottom: `매매일지`, `포트폴리오`, `분석`.
- Theme, CSV exports, KIS Sync, current role, and logout move into one menu.
- The mobile subtitle is hidden and navigation never wraps.
- Safe-area padding prevents overlap with browser or device controls.
- No fake username or non-functional account-management button is displayed.
- The account trigger is reusable so Phase B can later show the real username.

**Browser acceptance:** 360x800, 390x844, 768px, and 1440x900; dark/light themes; no horizontal overflow; first content visible in initial viewport.

**Approval checkpoint:** User checks the new header and navigation on the real phone before A2.

## Step A2: Journal Workflow

**Owner:** Gemini Anti IDE

**Files:** `app/templates/journal.html`, `app/static/style.css`, journal regression tests.

- Desktop keeps a dense, customizable table.
- Mobile uses readable trade cards instead of compressing the full table.
- Search and filters become a compact row and mobile filter sheet.
- Add a compact quick-record `+` action without covering content.
- Review the existing edit drawer rather than rebuilding it.
- Move its inline styles to shared CSS.
- Desktop uses a side drawer; mobile uses a full-screen editor.
- Add pending, success, error, validation, focus management, Escape close, and unsaved-change protection.
- Test BUY, SELL, CASHFLOW, SL_UPDATE, and REVIEW separately.
- Fix numeric-value handling so valid zeroes are not lost through `value || ""`.
- Keep image, edit, and more actions compact; no giant Gallery/Camera buttons over content.

**Browser acceptance:** View/filter/edit each event type using an isolated test DB; verify keyboard and touch behavior; zero console errors.

**Approval checkpoint:** User tests one view, one filter, and one edit on mobile and PC.

## Step A3: Analytics Simplification

**Owner:** Gemini Anti IDE

**Files:** `app/templates/stats.html`, `app/static/style.css`, stats UI tests. Do not delete backend calculations in this phase.

- Rename M2 to `기간 수익률` and make it the primary return metric.
- Rename Realized Return to `확정 수익률`.
- Hide M1 under `고급 지표` with a plain-language explanation.
- Default metrics: period return, realized PnL, win rate, and MDD.
- Replace separate daily/weekly/monthly/yearly charts with one chart and a segmented period control.
- Move Monthly Check into an analytics tab.
- Preserve ApexCharts lifecycle cleanup and theme switching.
- Keep advanced values available without overwhelming the default view.

**Browser acceptance:** Every chart container has exactly one ApexCharts canvas before and after period/theme changes; no console errors.

**Approval checkpoint:** User confirms the remaining statistics are useful and understandable.

## Step A4: Portfolio Simplification

**Owner:** Gemini Anti IDE

**Files:** `app/templates/portfolio.html`, `app/static/style.css`, portfolio UI tests.

- Prioritize total value, cash, unrealized PnL, and open risk.
- Desktop retains the detailed table.
- Mobile shows ticker cards with expandable lot details.
- Market refresh has clear loading, success, stale, and failure states.
- Empty portfolios and missing prices have intentional empty/error states.

**Approval checkpoint:** User checks a ticker with multiple lots on mobile and PC.

## Step A5: Phase A Verification and Release

**Owner:** Gemini executes; Codex reviews; User approves deployment.

- Run the existing 35-test suite excluding `tests/test_japan_market.py`.
- Run new focused UI regression tests.
- Capture desktop/mobile screenshots for all three primary screens.
- Verify dark/light theme, keyboard flow, 44px touch targets, safe areas, and no overflow.
- Confirm `git diff` contains no runtime DB, uploads, environment file, or secret.
- Codex reviews the branch diff and evidence.
- Gemini pushes only after review; merge/deploy only after user approval.
- User performs final production checks; Gemini records non-secret rollout evidence.

---

# Phase B: Invite-Only Multi-User Portal

Start Phase B only after Phase A is stable in production. Use a new branch and a new detailed plan.

## Step B0: Security Design Review

**Owner:** Gemini drafts; Codex reviews; User approves.

- Define `User`, `Invite`, and `PasswordReset` models.
- Usernames are unique, normalized, and 3-32 characters.
- Passwords use Argon2id and a minimum length of 12.
- Invites expire after 24 hours, work once, and are stored only as hashes.
- System administrators manage accounts but cannot browse user trading data by default.
- SQLite remains for the initial small invited group; PostgreSQL is a later scaling project.

## Step B1: Ownership Migration

**Owner:** Gemini Anti IDE

- Add `user_id` ownership to TradeGroup, Lot, Event, Setting, BrokerExecution, and BrokerSyncState.
- Keep Symbol as shared reference metadata.
- Validate that SellAllocation connects resources belonging to the same user.
- Create the first owner account and assign all existing data to it.
- Test the migration against a DB copy with backup, row counts, hashes, integrity check, and rollback.

**Approval checkpoint:** Codex reviews migration code and isolation tests before any operational migration.

## Step B2: Login and Invitations

**Owner:** Gemini Anti IDE

- Implement `/login`, logout, invite acceptance, account lock, and one-time password reset.
- Session contains user ID, expiry, and per-user auth version in a signed Secure/HttpOnly/SameSite cookie.
- Rate-limit by both IP and normalized username without revealing whether an account exists.
- The user menu prepared in A1 now displays the real username and account actions.

## Step B3: Tenant Isolation

**Owner:** Gemini implements; Codex performs a dedicated security review.

- Every read/write service requires the authenticated `user_id`.
- Journal, Portfolio, Stats, Monthly Check, KIS, exports, and uploads are tenant-scoped.
- Uploads live below `data/uploads/<user_id>/` and require ownership checks.
- Cross-user event, lot, group, image, export, and statistics requests return 404 or 403.
- Automated tests create users A and B and attempt every cross-user access path.

## Step B4: Token Authentication Retirement

**Owner:** Gemini proposes; User approves cutover.

- Deploy account login while temporarily retaining old token access.
- Verify owner login and existing data ownership.
- Disable old token routes only after account flows pass.
- Remove obsolete token settings and verify old token URLs return 404 or 410.

## Step B5: Phase B Verification and Release

**Owner:** Gemini executes isolated browser tests; Codex reviews; User deploys/approves.

- Test admin invite creation, friend signup, login, logout, lock, and reset.
- Test two users with clearly different data and prove mutual isolation.
- Use only test DB/uploads for browser mutations.
- Run all existing and new security tests.
- Back up operational data before migration.
- User performs secret entry and all required `sudo` commands directly.
- Verify production access without exposing credentials or personal trade details.

---

## 3. Recommended Handoff Sequence

1. User sends Step A0 prompt to Gemini.
2. Gemini returns plan and baseline screenshots without implementation.
3. User sends those outputs to Codex for review.
4. User approves A1; Gemini implements and browser-tests only A1.
5. User performs phone acceptance, then repeats the review cycle for A2-A4.
6. Codex reviews the complete Phase A diff and verification evidence.
7. User approves merge and production deployment.
8. After Phase A is stable, repeat the same plan-review-implement cycle for B0-B5.

## 4. Final Acceptance Criteria

- Mobile header consumes no more than 64px of app viewport height.
- Primary navigation contains only Journal, Portfolio, and Analytics.
- Journal reading, filtering, editing, and quick entry work on PC and mobile.
- Default analytics are understandable without knowing M1/M2 terminology.
- Production browser testing never alters real trading data unintentionally.
- Every private record and uploaded file is inaccessible to every other user.
- Existing data remains intact and belongs to the initial owner after migration.
