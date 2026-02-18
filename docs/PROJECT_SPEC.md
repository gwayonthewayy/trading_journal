# Trading Journal Project Spec (Handoff)

이 문서는 `trading_journal` 프로젝트를 다른 개발자 또는 Codex가 중단 없이 이어서 개발하기 위한 기준 명세다.

## 1. 프로젝트 목표

- 단일 사용자(개인) 기준의 트레이딩 저널/포트폴리오 웹앱 제공
- 거래 이벤트를 누적 기록하고, 포트폴리오/통계/트레이드 상세를 조회
- 관리자(Admin)만 쓰기 가능, 조회(Viewer)는 읽기 전용
- 쓰기 성공 시 SQLite DB 자동 백업

## 2. 기술 스택

- Python 3.12
- FastAPI + Jinja2
- SQLModel + SQLite
- Poetry
- yfinance (벤치마크 수익률)

## 3. 폴더 구조와 책임

- `app/main.py`: FastAPI 라우팅, 권한 의존성 연결, 템플릿 렌더링
- `app/services.py`: 핵심 도메인 로직(매수/매도/SL/통계/CSV/백업)
- `app/models.py`: SQLModel 테이블 스키마
- `app/schemas.py`: 요청/응답 스키마(Pydantic)
- `app/security.py`: 세션 토큰, 쿠키, 관리자 로그인 rate-limit
- `app/config.py`: 보안 환경변수 로딩/검증
- `app/database.py`: DB 엔진/세션/초기화
- `app/templates/*`: UI 페이지
- `app/static/style.css`: 공통 스타일
- `data/db.sqlite`: 운영 DB 파일
- `data/backups/*.sqlite`: 자동 백업 보관본

## 4. 도메인 모델 요약

- `Symbol`: 종목 마스터
- `TradeGroup`: 트레이드 묶음(제목/리뷰)
- `Lot`: 매수 단위 포지션(열린 수량/SL/TP 포함)
- `Event`: 저널 원장(BUY, SELL, SL_UPDATE, CASHFLOW, REVIEW)
- `SellAllocation`: SELL 이벤트와 Lot 간 수량 매핑
- `Setting`: 계산 설정(기준통화, 리스크 분모, 추정 청산 수수료율)

핵심 불변조건:
- 모든 포지션 상태는 `Event` 타임라인에서 재구성 가능해야 한다.
- SELL 할당 수량 합은 해당 시점 open qty를 초과하면 안 된다.
- 이벤트 수정/삭제 후에도 lot 수량이 음수가 되면 안 된다.

## 5. 인증/권한 모델

- 진입 URL:
  - Viewer: `/access/view/{TJ_VIEWER_TOKEN}`
  - Admin: `/access/admin/{TJ_ADMIN_TOKEN}` (+ 비밀번호)
- 세션 쿠키(`tj_session`)는 서명 기반이며 `Secure`, `HttpOnly`, `SameSite=Strict`
- 권한:
  - Viewer: 읽기 API + 페이지 조회
  - Admin: 읽기 + 쓰기 + CSV export
- `TJ_AUTH_VERSION` 변경 시 기존 세션 무효화
- `TJ_ENV=prod`에서는 `/docs`, `/openapi.json`, `/redoc` 비활성화

## 6. 주요 API

쓰기(Admin):
- `POST /api/buy`
- `POST /api/sell`
- `POST /api/lot/sl`
- `POST /api/cashflow`
- `POST /api/review`
- `PATCH /api/events/{event_id}`
- `DELETE /api/events/{event_id}`

읽기(Viewer 이상):
- `GET /api/portfolio`
- `GET /api/journal`
- `GET /api/stats`
- `GET /api/benchmark/returns?symbol=SPY|QQQ|IWM|FFTY`

내보내기(Admin):
- `GET /export/events.csv`
- `GET /export/lots.csv`
- `GET /export/sell_allocations.csv`

페이지:
- `/journal`, `/portfolio`, `/stats`, `/trades/{trade_group_id}`

## 7. 핵심 계산/비즈니스 규칙

- BUY 생성 시 `Lot` + `Event(BUY)` 동시 생성
- SELL 생성 시:
  - 할당(`allocations`) 유효성 검증
  - 평균단가 기반 `realized_pnl = (sell_price - avg_cost) * sell_qty - fee`
  - `SellAllocation` 레코드 생성
- SL 업데이트는 `SL_UPDATE` 이벤트를 남기고 lot snapshot 동기화
- 저널/통계는 이벤트 타임라인(`ts`, `id` 오름차순) 기반으로 계산
- BE(본절) 판정:
  - reason에 `BE/breakeven/본절/본전/손익분기` 패턴 포함
  - 또는 `|realized_pnl| <= 10 USD`
- 쓰기 API 커밋 성공 시 백업 생성, 최대 200개 유지

## 8. 실행 및 로컬 개발

1. 의존성 설치
   - `poetry install`
2. 필수 환경변수 설정
   - `TJ_ENV`
   - `TJ_SIGNING_SECRET` (32 bytes 이상)
   - `TJ_VIEWER_TOKEN`
   - `TJ_ADMIN_TOKEN`
   - `TJ_ADMIN_PASSWORD_HASH`
   - `TJ_AUTH_VERSION` (기본 1)
   - `TJ_VIEWER_SESSION_HOURS` (기본 168)
   - `TJ_ADMIN_SESSION_HOURS` (기본 12)
3. 실행
   - `poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000`

운영 권장:
- 앱은 `127.0.0.1` 바인딩 유지
- 외부 공개는 Cloudflare Tunnel 사용
- `data/` 디렉토리 주기 백업

## 9. Codex 인수인계 규칙

새 작업 시작 시 최소 확인 파일:
- `README.md`
- `docs/PROJECT_SPEC.md` (이 문서)
- 변경 대상 모듈(`app/main.py`, `app/services.py`, `app/models.py`)

기능 추가 체크리스트:
1. 스키마(`schemas.py`)와 서비스(`services.py`)를 먼저 정의
2. 라우팅(`main.py`)에 권한 가드 정확히 연결
3. 이벤트 정합성(할당, open qty, 음수 수량 방지) 보장
4. 쓰기 경로에서 커밋/롤백/백업 흐름 유지
5. UI 변경 시 대응 템플릿까지 함께 수정

변경 시 금지사항:
- 이벤트 재계산 로직을 우회하는 임시 업데이트 금지
- 인증 우회용 하드코딩 토큰/비밀번호 금지
- 백업 로직 삭제/무력화 금지

## 10. 공유(오픈/협업) 가이드

- 소스 공유 시 비밀값은 절대 커밋하지 않는다.
- `.env`/실서버 토큰/비밀번호 해시는 저장소 제외
- 반드시 포함할 파일:
  - `README.md`
  - `docs/PROJECT_SPEC.md`
  - `pyproject.toml`, `poetry.lock`
- 새 기여자는 먼저 본 문서의 체크리스트를 기준으로 작업한다.

