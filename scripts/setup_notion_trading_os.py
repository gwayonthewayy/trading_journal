#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

NOTION_VERSION = "2022-06-28"


def _env_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("TJ_RUNTIME_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root / ".env.runtime")
    candidates.append(Path.cwd() / ".env.runtime")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _load_env_file_if_needed() -> None:
    if os.getenv("NOTION_TOKEN") and os.getenv("NOTION_PARENT_PAGE_ID"):
        return

    env_path = next((p for p in _env_candidates() if p.exists()), None)
    if env_path is None:
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _normalize_page_id(page_id: str) -> str:
    normalized = page_id.strip().replace("-", "")
    if len(normalized) != 32:
        raise RuntimeError("NOTION_PARENT_PAGE_ID must be a 32-character page id.")
    return normalized


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = request.Request(
            url=f"https://api.notion.com{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
        )
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Notion API error ({exc.code}) on {path}: {detail}") from exc

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        return self._request("POST", "/v1/databases", payload)

    def update_database(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        payload = {"properties": properties}
        return self._request("PATCH", f"/v1/databases/{database_id}", payload)


def _build_journal_properties() -> dict[str, Any]:
    return {
        "종목명": {"title": {}},
        "티커": {"rich_text": {}},
        "시장": {"select": {"options": [{"name": "국장"}, {"name": "미장"}, {"name": "홍장"}]}},
        "현재가": {"number": {"format": "number_with_commas"}},
        "총평(누적)": {"rich_text": {}},
    }


def _build_positions_properties(journal_db_id: str) -> dict[str, Any]:
    return {
        "포지션명": {"title": {}},
        "시작일": {"date": {}},
        "종료일": {"date": {}},
        "상태": {"select": {"options": [{"name": "OPEN"}, {"name": "CLOSED"}]}},
        "현재가": {"number": {"format": "number_with_commas"}},
        "총평": {"rich_text": {}},
        "종목 저널": {
            "relation": {
                "database_id": journal_db_id,
                "type": "dual_property",
                "dual_property": {"synced_property_name": "포지션 목록"},
            }
        },
    }


def _build_fills_properties(positions_db_id: str) -> dict[str, Any]:
    return {
        "기록명": {"title": {}},
        "시장": {"select": {"options": [{"name": "국장"}, {"name": "미장"}, {"name": "홍장"}]}},
        "종목명": {"rich_text": {}},
        "티커": {"rich_text": {}},
        "체결일시": {"date": {}},
        "구분": {"select": {"options": [{"name": "매수"}, {"name": "매도"}]}},
        "수량": {"number": {"format": "number"}},
        "체결가": {"number": {"format": "number_with_commas"}},
        "수수료": {"number": {"format": "number_with_commas"}},
        "근거": {"rich_text": {}},
        "차트사진": {"files": {}},
        "피드백": {"rich_text": {}},
        "포지션(라운드)": {
            "relation": {
                "database_id": positions_db_id,
                "type": "dual_property",
                "dual_property": {"synced_property_name": "체결내역"},
            }
        },
        "매수수량": {"formula": {"expression": 'if(prop("구분") == "매수", prop("수량"), 0)'}},
        "매도수량": {"formula": {"expression": 'if(prop("구분") == "매도", prop("수량"), 0)'}},
        "매수금액": {
            "formula": {
                "expression": 'if(prop("구분") == "매수", prop("수량") * prop("체결가") + prop("수수료"), 0)'
            }
        },
        "매도금액": {
            "formula": {
                "expression": 'if(prop("구분") == "매도", prop("수량") * prop("체결가") - prop("수수료"), 0)'
            }
        },
    }


def _positions_extensions() -> dict[str, Any]:
    return {
        "매수총수량": {
            "rollup": {"relation_property_name": "체결내역", "rollup_property_name": "매수수량", "function": "sum"}
        },
        "매도총수량": {
            "rollup": {"relation_property_name": "체결내역", "rollup_property_name": "매도수량", "function": "sum"}
        },
        "매수총금액": {
            "rollup": {"relation_property_name": "체결내역", "rollup_property_name": "매수금액", "function": "sum"}
        },
        "매도총금액": {
            "rollup": {"relation_property_name": "체결내역", "rollup_property_name": "매도금액", "function": "sum"}
        },
        "보유수량": {"formula": {"expression": 'prop("매수총수량") - prop("매도총수량")'}},
        "평단가": {
            "formula": {
                "expression": 'if(prop("매수총수량") > 0, prop("매수총금액") / prop("매수총수량"), 0)'
            }
        },
        "실현수익": {"formula": {"expression": 'prop("매도총금액") - prop("매수총금액")'}},
        "미실현수익": {
            "formula": {
                "expression": 'if(prop("보유수량") > 0, (prop("현재가") - prop("평단가")) * prop("보유수량"), 0)'
            }
        },
        "수익률": {
            "formula": {
                "expression": 'if(prop("매수총금액") > 0, prop("실현수익") / prop("매수총금액"), 0)'
            }
        },
        "결과": {
            "formula": {
                "expression": 'if(prop("실현수익") > 0, "WIN", if(prop("실현수익") < 0, "LOSS", "FLAT"))'
            }
        },
        "주차": {
            "formula": {
                "expression": 'if(empty(prop("종료일")), formatDate(prop("시작일"), "YYYY-[W]WW"), formatDate(prop("종료일"), "YYYY-[W]WW"))'
            }
        },
        "월": {
            "formula": {
                "expression": 'if(empty(prop("종료일")), formatDate(prop("시작일"), "YYYY-MM"), formatDate(prop("종료일"), "YYYY-MM"))'
            }
        },
    }


def _journal_extensions() -> dict[str, Any]:
    return {
        "누적 실현수익": {
            "rollup": {"relation_property_name": "포지션 목록", "rollup_property_name": "실현수익", "function": "sum"}
        },
        "누적 미실현수익": {
            "rollup": {"relation_property_name": "포지션 목록", "rollup_property_name": "미실현수익", "function": "sum"}
        },
        "평균 수익률": {
            "rollup": {"relation_property_name": "포지션 목록", "rollup_property_name": "수익률", "function": "average"}
        },
        "총 포지션 수": {
            "rollup": {"relation_property_name": "포지션 목록", "rollup_property_name": "포지션명", "function": "count_all"}
        },
    }


def _safe_update_database(client: NotionClient, database_id: str, properties: dict[str, Any], label: str) -> bool:
    try:
        client.update_database(database_id, properties)
        print(f"[OK] {label}")
        return True
    except RuntimeError as exc:
        print(f"[WARN] {label} failed: {exc}")
        return False


def main() -> int:
    _load_env_file_if_needed()
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID", "").strip()
    if not notion_token:
        raise RuntimeError("Missing NOTION_TOKEN")
    if not parent_page_id:
        raise RuntimeError("Missing NOTION_PARENT_PAGE_ID")

    parent_page_id = _normalize_page_id(parent_page_id)
    client = NotionClient(notion_token)

    journal_db = client.create_database(
        parent_page_id=parent_page_id,
        title="종목 저널 DB",
        properties=_build_journal_properties(),
    )
    journal_db_id = journal_db["id"]
    print(f"[OK] 종목 저널 DB created: {journal_db_id}")

    positions_db = client.create_database(
        parent_page_id=parent_page_id,
        title="포지션(라운드) DB",
        properties=_build_positions_properties(journal_db_id),
    )
    positions_db_id = positions_db["id"]
    print(f"[OK] 포지션(라운드) DB created: {positions_db_id}")

    fills_db = client.create_database(
        parent_page_id=parent_page_id,
        title="체결내역 DB",
        properties=_build_fills_properties(positions_db_id),
    )
    fills_db_id = fills_db["id"]
    print(f"[OK] 체결내역 DB created: {fills_db_id}")

    positions_done = _safe_update_database(
        client,
        positions_db_id,
        _positions_extensions(),
        "포지션(라운드) DB rollup/formula properties",
    )
    journal_done = _safe_update_database(
        client,
        journal_db_id,
        _journal_extensions(),
        "종목 저널 DB rollup properties",
    )

    print("\nDone. Next in Notion:")
    if not positions_done or not journal_done:
        print("1) 포지션(라운드) DB에서 수동으로 Rollup/Formula를 추가하세요.")
        print("2) 종목 저널 DB에서 포지션 목록 기준 Rollup을 수동 추가하세요.")
        print("3) 체결내역 템플릿에 근거/차트/피드백 입력 섹션을 추가하세요.")
    else:
        print("1) 종목 저널 DB 안에 linked view로 포지션(라운드) DB, 체결내역 DB 추가")
        print("2) 포지션(라운드) DB를 월/주 그룹 뷰로 저장")
        print("3) 체결내역 템플릿에 근거/차트/피드백 입력 섹션 추가")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
