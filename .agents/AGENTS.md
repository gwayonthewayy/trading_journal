# Trading Journal Project Rules (프로젝트 작업 규칙)

이 프로젝트에서 작업할 때는 다음 규칙을 항상 준수하십시오.

## 1. 작업 시작 시 (On Start)
- `git status --short --branch` 상태를 가장 먼저 확인합니다.
- `git log -n 5 --oneline` 커밋 히스토리를 확인합니다.
- 관련 handoff 문서(docs/agent-handoffs/)와 롤아웃 로그(docs/operations/2026-06-21-production-rollout-log.md)를 먼저 확인하고 읽어야 합니다.

## 2. 작업 중 (During Development)
- 의미 있는 변경 단위마다 커밋(Commit)을 생성합니다.
- `.env.runtime`, `data/db.sqlite`, `data/uploads`는 절대로 커밋하거나 터미널/로그에 출력하거나 수정해서는 안 됩니다.
- 토큰(Tokens), 비밀번호(Passwords), 쿠키(Cookies), 서명 키(Signing Secret), 토큰 URL 원문은 절대 기록하거나 유출하지 마십시오.

## 3. 작업 종료 시 (On Completion)
반드시 다음 경로에 handoff 문서를 업데이트합니다.
- **경로**: `docs/agent-handoffs/YYYY-MM-DD-작업명.md`
- **포함할 내용**:
  - 작업 목표
  - 현재 브랜치
  - 기준 main HEAD
  - 작업 커밋 SHA
  - 변경 파일 목록
  - 실행한 테스트 명령과 결과
  - 브라우저 검증 여부
  - 서비스 재시작 여부
  - 운영 반영 여부
  - 남은 pending 항목
  - 다음 에이전트가 이어받을 때 확인할 명령어
  - 다음 단계 추천

## 4. 운영 배포/서비스 변경 발생 시 (Operations)
- `docs/operations/2026-06-21-production-rollout-log.md` 문서에도 관련 변경 및 검증 사항을 함께 기록합니다.

## 5. 로그 기밀 유지 (Log Privacy)
- 원문 `transcript.jsonl`은 절대 Git에 커밋하지 않습니다.
- 필요한 경우 `/opt/gyu/private-agent-logs/` 경로 아래에만 저장하고, `chmod 600` 권한으로 제한합니다.

## 6. 최종 보고 제한 (Reporting Constraint)
최종 보고 시에는 다음 항목만 기재하십시오.
- 커밋 SHA (Commit SHA)
- push 여부 (Pushed Status)
- 테스트 결과 (Test Results)
- git status (Git Status)
- 다음 단계 (Next Steps)
