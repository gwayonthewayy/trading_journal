# Auth A+B Login Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존의 불편한 토큰 링크 접속을 넘어 일반적인 포털 스타일의 `/login` 경로에서 ID/PW로 로그인할 수 있는 구조를 만듭니다. (기존 토큰 접근은 폴백(Fallback)으로 온전히 유지)

**Architecture:** 
1. `app/auth_service.py`를 신규 생성하여 계정 정보 검증 및 로그인 제어를 얇은 추상화 경계 모듈로 격리합니다.
2. `app/config.py` 및 `SecuritySettings`에 관리자 사용자 이름(`TJ_ADMIN_USERNAME`)을 불러오는 환경변수 설정을 추가합니다.
3. `app/main.py`에 `/login` 경로(GET 및 POST)를 추가하여 ID/PW를 검증하고 세션을 발급하는 플로우를 구현합니다.
4. 사용자 메뉴(User Menu Drawer)에 계정, 설정(비활성화 메뉴 구조), 로그아웃 구조와 ADMIN 역할 피약(Role Pill)을 유기적으로 배치합니다.
5. 모든 코드는 `tests/test_auth_login.py`를 통해 안전하게 자동 검증(TDD)을 수행합니다.

**Tech Stack:** FastAPI, Jinja2, Uvicorn, unittest

## Global Constraints
- **보안 최우선:** 런타임 토큰, 패스워드 해시, `.env.runtime` 파일의 구체적인 값 등은 git 커밋, stdout 로그, 채팅 응답에 절대로 출력하거나 포함하지 않는다.
- **폴백 보존:** 기존 `/access/admin/{admin_token}`, `/access/view/{viewer_token}` 및 `/access` 자체의 가이드 경로는 어떠한 수정이나 충돌 없이 완벽히 유지한다.
- **구현 금지:** 이 계획서는 계획 단계 문서이므로, 사용자 승인이 나기 전까지 실제 어플리케이션 코드를 수정하지 않는다.
- **버전 관리:** `.env.runtime`, `data/db.sqlite`, `data/uploads` 등은 git에 추가되거나 커밋되지 않도록 확인한다.

---

### Task Deploy-Preflight: 환경 변수 안전 검사 및 사전 준비
**Files:**
- Read/Modify: `.env.runtime` (git 추적에서 엄격히 제외됨)

- [ ] **Step 1: .env.runtime 내 TJ_ADMIN_USERNAME 존재 확인**
  - 값 자체를 절대 콘솔/로그/채팅에 출력하지 않고, `grep` 또는 python 스크립트로 해당 키의 설정 여부만 점검.
- [ ] **Step 2: 누락 시 사용자 확인 후 주입**
  - 운영 배포 이전에 `TJ_ADMIN_USERNAME`이 존재하지 않을 시, 사용자 승인을 득한 후 값 노출 없이 원자적(Atomic)으로 값을 `.env.runtime` 파일에 직접 추가.
  - **위험성 경고:** 운영 환경(`TJ_ENV`가 `dev` 또는 `test`가 아님)에서 `TJ_ADMIN_USERNAME`이 누락된 상태로 메인 브랜치가 배포되고 서비스가 재시작되면 서버가 `RuntimeError`를 발생시켜 기동에 실패하게 됨을 명시함.
  - preflight 단계 완료 전까지는 어떠한 `systemctl restart` 및 재시작 행위도 일절 금지함.

---

### Task Auth-0: 소스 분석 및 기존 정책 검사
**Files:**
- Read: `app/security.py` (기존 세션 쿠키 정책 분석)
- Read: `app/config.py` (기존 환경 변수 구성 검토)

- [x] **Step 1: 기존 세션 흐름 및 쿠키 정책 요약 완료**
  - 기존 세션 쿠키는 `tj_session` 키를 사용하며, 서명된 JWT 유사 형태(`payload_b64.signature_b64`)로 구성됨.
  - 관리자 암호 검증은 `app/security.py` 내 `verify_admin_password()`에서 Argon2id 또는 PBKDF2를 지원함.
  - 쿠키 발급 및 삭제는 `app/security.py` 내의 `set_session_cookie` 및 `clear_session_cookie` 함수가 정의되어 있으며, 기존 동작 및 구조를 그대로 상속하여 유지함.

---

### Task Auth-1: 환경 변수 파싱 및 Auth Service 설계
**Files:**
- Modify: `app/config.py`
- Create: `app/auth_service.py`
- Test: `tests/test_auth_login.py` (TDD 작성)

**Interfaces:**
- Consumes: `os.getenv("TJ_ADMIN_USERNAME")`, `os.getenv("TJ_ENV")`
- Produces: `SecuritySettings.admin_username` 속성 및 `authenticate_admin(username, password) -> bool`

- [ ] **Step 1: 환경 변수 및 인증 서비스 유닛 테스트 작성**
  - `tests/test_auth_login.py` 파일 생성 후 아래 테스트 함수 구현:
    - `test_env_preflight_prod_missing_username_raises_error`: `TJ_ENV=prod`이고 `TJ_ADMIN_USERNAME`이 없을 때 `RuntimeError` 발생 확인.
    - `test_env_preflight_dev_missing_username_uses_default`: `TJ_ENV=dev`이고 `TJ_ADMIN_USERNAME`이 없을 때 `"admin"` 기본값 확인.
    - `test_auth_service_admin_success`: 올바른 관리자 아이디 및 암호 전달 시 True 반환 검증.
    - `test_auth_service_admin_invalid_username`: 틀린 아이디 전달 시 False 반환 검증.
    - `test_auth_service_admin_invalid_password`: 틀린 암호 전달 시 False 반환 검증.
- [ ] **Step 2: 테스트 실행 및 실패 확인**
  - Run: `.venv/bin/python -m unittest tests.test_auth_login`
  - Expected: FAIL (모듈 미비로 인한 에러)
- [ ] **Step 3: app/config.py 수정**
  - `SecuritySettings` 데이터클래스에 `admin_username: str` 속성을 추가.
  - `load_security_settings()` 내에 환경변수를 바인딩하고, `TJ_ENV` 환경에 따른 안전 실패(Safe failure) 로직 추가.
- [ ] **Step 4: app/auth_service.py 구현**
  - `authenticate_admin(username, password, settings)` 함수 구현. (내부적으로 `verify_admin_password()` 및 `settings.admin_username` 대조)
  - 나중에 `users` 테이블 기반 멀티유저 구조로 손쉽게 교체 가능하도록 결합도를 낮추는 얇은 헬퍼 경계 모듈로 구성.
- [ ] **Step 5: 테스트 실행 및 통과 확인**
  - Run: `.venv/bin/python -m unittest tests.test_auth_login`
  - Expected: PASS
- [ ] **Step 6: 커밋**
  - Commit: `git add app/config.py app/auth_service.py tests/test_auth_login.py && git commit -m "feat(auth): config updates and auth_service foundation (Auth-1)"`

---

### Task Auth-2: 로그인/로그아웃 라우팅 구현
**Files:**
- Modify: `app/main.py`
- Modify: `app/security.py` (Secure 쿠키 로컬 이슈 확인 시 한정적으로 보정 적용 예정)
- Create: `app/templates/login.html`
- Test: `tests/test_auth_login.py`

**Interfaces:**
- Consumes: `/login` (GET, POST), `/logout` (POST)
- Produces: 세션 쿠키 발급 및 리디렉션

- [ ] **Step 1: 로그인 라우팅 테스트 코드 추가**
  - `tests/test_auth_login.py` 내 `TestClient`를 구성하여 아래 테스트 함수 추가:
    - `test_login_page_renders_with_dark_glass_style`: `/login` GET 시 HTTP 200 반환 및 스타일 요소(Dark/Glass) 확인.
    - `test_login_success_redirects_and_sets_cookie`: 올바른 자격 증명 전송 시 세션 쿠키 발급 및 `/journal` 리디렉션 확인.
    - `test_login_failure_returns_200_with_generic_message`: 로그인 실패 시 HTTP 200 상태 코드로 폼을 반환하고 "아이디 또는 비밀번호가 올바르지 않습니다." 에러 메시지가 폼에 노출되는지 검증.
    - `test_protected_page_redirects_to_login_for_unauthenticated`: 비인증 사용자가 `/journal` 등 접근 시 `/login`으로 리디렉션 유도 검증.
    - `test_access_page_continues_to_serve_as_fallback_info`: `/access` 자체 가이드 화면은 깨지지 않고 HTTP 200을 제공하는지 검증.
- [ ] **Step 2: 테스트 실행 및 실패 확인**
  - Run: `.venv/bin/python -m unittest tests.test_auth_login`
  - Expected: FAIL
- [ ] **Step 3: app/security.py 분석 및 로컬 HTTP 보정 (필요시 최소 수정)**
  - 로컬 HTTP 테스트에서 `Secure` 속성으로 인해 실제 쿠키 전달 실패 문제가 발생하는 경우에만 조건부로 `secure` 속성을 `settings.env.lower() == "prod"`로 우회하도록 최소 수정 조치 적용. (문제 무재현 시 기존 동작 유지)
- [ ] **Step 4: app/templates/login.html 템플릿 생성**
  - 기존 `tjgyu.site`의 다크/글래스(Dark/Glass) 스타일과 모바일 반응형 디자인 톤에 맞춘 로그인 폼 구성. (이질적인 카드로 튀지 않게 작성)
- [ ] **Step 5: app/main.py 수정**
  - `/login` GET 및 POST 컨트롤러 구현.
  - POST 처리 시 `authenticate_admin` 서비스를 호출해 실패 시 HTTP 200으로 generic message("아이디 또는 비밀번호가 올바르지 않습니다.")가 적힌 템플릿 반환.
  - 비인증 시의 자동 유도 지점을 `/access` 대신 `/login`으로 변경하도록 `_require_viewer_page_role` 수정.
  - 기존 토큰 기반 폴백 라우트 `/access/admin/{admin_token}` 및 `/access/view/{viewer_token}`은 무수정 상태로 유지.
- [ ] **Step 6: 테스트 실행 및 통과 확인**
  - Run: `.venv/bin/python -m unittest tests.test_auth_login`
  - Expected: PASS
- [ ] **Step 7: 커밋**
  - Commit: `git add app/main.py app/security.py app/templates/login.html tests/test_auth_login.py && git commit -m "feat(auth): login and logout routes with custom style (Auth-2)"`

---

### Task Auth-3: 사용자 메뉴 구조화
**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/static/style.css`

**Interfaces:**
- Consumes: Jinja context의 `auth_role` 및 `can_write`
- Produces: 계정, 설정(disabled 항목), 로그아웃 구조를 담은 User Menu Drawer 렌더링

- [ ] **Step 1: base.html 템플릿 수정**
  - 햄버거 메뉴를 눌렀을 때 나오는 `#user-menu-drawer`의 리스트에 `계정(Account)`, `설정(Settings)` 링크 추가.
  - **계정/설정 구현 보정:** 실제 `/account` 및 `/settings` 라우트는 이번 범위에서 구현하지 않으므로, 메뉴에 `disabled` / `non-clickable` 플레이스홀더 스타일로 렌더링해 404 에러가 나지 않도록 유연하게 조치함.
  - `로그아웃` 버튼이 POST 방식으로 `/logout`으로 요청을 전송하도록 폼 연동 확인.
  - 현재 인증된 역할(`ADMIN` 또는 `VIEWER`)을 표시해 주는 역할 필약(Role Pill)을 가독성 있게 배치.
  - 계정 정보(Username)는 보안을 위해 기본적으로는 노출하지 않거나, 별도 플레이스홀더 처리.
- [ ] **Step 2: CSS 스타일링 및 반응형 점검**
  - 모바일(하단 sticky nav) 및 데스크탑 앱 셸 레이아웃과 간섭이 없는지 점검.
- [ ] **Step 3: 커밋**
  - Commit: `git add app/templates/base.html app/static/style.css && git commit -m "feat(auth): add settings skeleton and update user menu drawer (Auth-3)"`

---

### Task Auth-4: 유닛 테스트 및 자동화 검증
**Files:**
- Run: 전체 테스트

- [ ] **Step 1: 전체 테스트 모듈 검증**
  - `test_japan_market.py`를 제외한 모든 테스트를 정상 수행하여 사이드 이펙트가 없는지 검증.
  - Run: `.venv/bin/python -m unittest -v tests.test_app_shell_source tests.test_corporate_actions tests.test_deploy_templates tests.test_kis_admin tests.test_kis_client tests.test_kis_config tests.test_kis_sync tests.test_miraeasset_importers tests.test_portfolio_source tests.test_stats_and_theme_templates tests.test_auth_login`
- [ ] **Step 2: Git 파일 보존 검증**
  - Run: `git status --short` 및 `git diff --check`
  - Expected: `.env.runtime`, `data/db.sqlite`, `data/uploads`가 수정 목록에 들어있지 않아야 함.

---

### Task Auth-5: 브라우저 수동 검증 계획
**Method:** Desktop/Mobile Viewport Acceptance Matrix

- [ ] **Step 1: 포트 확인 및 테스트 서버 구동**
  - 포트 `8002`, `8003`, `8010` 순서로 사용 중인지 확인하고, 비어 있는 포트를 선택하여 백그라운드로 테스트 서버 가동. (기존 프로세스 kill 금지)
- [ ] **Step 2: 브라우저 검증 수행**
  - **로그인 진입 검증:** 비인증 상태에서 `/journal` 등으로 접속 시 `/login`으로 강제 리디렉션되는지 확인.
  - **로그인 폼 렌더링:** `/login` 접속 시 반응형으로 폼과 에러 메시지가 잘 정돈되어 나오는지 확인 (360px, 390px, 1440px).
  - **로그인 실패 검증:** 잘못된 ID/PW 입력 시 콘솔 에러 없이 "아이디 또는 비밀번호가 올바르지 않습니다." 에러 메시지가 폼에 노출되는지 확인.
  - **로그인 성공 검증:** 올바른 ID/PW 입력 시 `/journal`로 정상 리디렉션되며, 세션 쿠키가 정상 발급되는지 확인. (기존 쿠키 발급/삭제 정책 유지)
  - **사용자 메뉴 검증:** 모바일/데스크탑 환경에서 메뉴 드로어 내에 계정(비활성), 설정(비활성), 로그아웃 항목이 잘 렌더링되는지 확인.
  - **로그아웃 검증:** 로그아웃 버튼을 눌렀을 때 세션 쿠키가 파괴되고 `/login`으로 정상 리디렉션되는지 확인.
  - **토큰 폴백 검증:** 기존 토큰 방식(`/access/view/<token>`, `/access/admin/<token>`)으로 접속 시 정상 로그인되어 리디렉션되는지 확인 (토큰 값 노출 절대 금지).
- [ ] **Step 3: 테스트 서버 프로세스 종료**
  - 검증 완료 후, 구동했던 테스트 서버의 PID를 정확하게 찾아 프로세스 안전 종료.
