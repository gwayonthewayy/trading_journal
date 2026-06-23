from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _runtime_env_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("TJ_RUNTIME_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    project_root = Path(__file__).resolve().parents[1]
    candidates.append(project_root / ".env.runtime")
    candidates.append(Path.cwd() / ".env.runtime")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_runtime_env_file() -> None:
    env_path = next((p for p in _runtime_env_candidates() if p.exists()), None)
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


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


@dataclass(frozen=True)
class SecuritySettings:
    env: str
    signing_secret: str
    viewer_token: str
    admin_token: str
    admin_password_hash: str
    auth_version: int
    viewer_session_hours: int
    admin_session_hours: int
    admin_username: str

    @property
    def docs_enabled(self) -> bool:
        return self.env.lower() != "prod"


def load_security_settings() -> SecuritySettings:
    _load_runtime_env_file()

    env = _require_env("TJ_ENV")
    signing_secret = _require_env("TJ_SIGNING_SECRET")
    viewer_token = _require_env("TJ_VIEWER_TOKEN")
    admin_token = _require_env("TJ_ADMIN_TOKEN")
    admin_password_hash = _require_env("TJ_ADMIN_PASSWORD_HASH")
    auth_version = _int_env("TJ_AUTH_VERSION", 1)
    viewer_session_hours = _int_env("TJ_VIEWER_SESSION_HOURS", 168)
    admin_session_hours = _int_env("TJ_ADMIN_SESSION_HOURS", 12)

    admin_username_raw = os.getenv("TJ_ADMIN_USERNAME")
    if admin_username_raw is not None and admin_username_raw.strip() != "":
        admin_username = admin_username_raw.strip()
    else:
        if env.lower() in ("dev", "test"):
            admin_username = "admin"
        else:
            raise RuntimeError("Missing required environment variable: TJ_ADMIN_USERNAME")

    if len(signing_secret.encode("utf-8")) < 32:
        raise RuntimeError("TJ_SIGNING_SECRET must be at least 32 bytes")
    if auth_version < 1:
        raise RuntimeError("TJ_AUTH_VERSION must be >= 1")
    if viewer_session_hours < 1:
        raise RuntimeError("TJ_VIEWER_SESSION_HOURS must be >= 1")
    if admin_session_hours < 1:
        raise RuntimeError("TJ_ADMIN_SESSION_HOURS must be >= 1")

    return SecuritySettings(
        env=env,
        signing_secret=signing_secret,
        viewer_token=viewer_token,
        admin_token=admin_token,
        admin_password_hash=admin_password_hash,
        auth_version=auth_version,
        viewer_session_hours=viewer_session_hours,
        admin_session_hours=admin_session_hours,
        admin_username=admin_username,
    )
