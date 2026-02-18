from __future__ import annotations

import base64
import hmac
import json
import time
from collections import defaultdict
from collections.abc import Callable
from hashlib import pbkdf2_hmac
from hashlib import sha256
from typing import Literal

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency fallback
    PasswordHasher = None  # type: ignore[assignment]
    InvalidHashError = VerificationError = VerifyMismatchError = Exception  # type: ignore[assignment]
from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.config import SecuritySettings

Role = Literal["viewer", "admin"]
COOKIE_NAME = "tj_session"

_password_hasher = PasswordHasher() if PasswordHasher is not None else None
_failed_attempts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 10 * 60


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def _sign(message: str, signing_secret: str) -> str:
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).digest()
    return _b64url_encode(signature)


def create_session_token(role: Role, settings: SecuritySettings) -> tuple[str, int]:
    now = int(time.time())
    max_age_hours = settings.admin_session_hours if role == "admin" else settings.viewer_session_hours
    expires_at = now + (max_age_hours * 3600)
    payload = {
        "role": role,
        "issued_at": now,
        "expires_at": expires_at,
        "auth_version": settings.auth_version,
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_raw)
    signature_b64 = _sign(payload_b64, settings.signing_secret)
    return f"{payload_b64}.{signature_b64}", expires_at


def _decode_session_token(token: str, settings: SecuritySettings) -> dict | None:
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload_b64, signature_b64 = parts
    expected = _sign(payload_b64, settings.signing_secret)
    if not hmac.compare_digest(expected, signature_b64):
        return None
    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def get_current_role(request: Request, settings: SecuritySettings) -> Role | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = _decode_session_token(token, settings)
    if not payload:
        return None

    role = payload.get("role")
    expires_at = payload.get("expires_at")
    auth_version = payload.get("auth_version")
    if role not in ("viewer", "admin"):
        return None
    if not isinstance(expires_at, int) or int(time.time()) >= expires_at:
        return None
    if auth_version != settings.auth_version:
        return None
    return role


def set_session_cookie(response: Response, token: str, expires_at: int) -> None:
    max_age = max(0, expires_at - int(time.time()))
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
        max_age=max_age,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )


def is_valid_viewer_token(token: str, settings: SecuritySettings) -> bool:
    return hmac.compare_digest(token, settings.viewer_token)


def is_valid_admin_token(token: str, settings: SecuritySettings) -> bool:
    return hmac.compare_digest(token, settings.admin_token)


def verify_admin_password(password: str, settings: SecuritySettings) -> bool:
    stored = settings.admin_password_hash

    if stored.startswith("pbkdf2_sha256$"):
        # Format: pbkdf2_sha256$<iterations>$<salt>$<digest_hex>
        parts = stored.split("$", 3)
        if len(parts) != 4:
            return False
        _, iter_s, salt, expected_hex = parts
        try:
            iterations = int(iter_s)
        except ValueError:
            return False
        if iterations < 1:
            return False
        derived = pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
        return hmac.compare_digest(derived, expected_hex)

    if _password_hasher is None:
        return False

    try:
        return _password_hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _prune_attempts(ip: str, now: float) -> list[float]:
    recent = [t for t in _failed_attempts.get(ip, []) if now - t <= RATE_LIMIT_WINDOW_SECONDS]
    _failed_attempts[ip] = recent
    return recent


def check_admin_rate_limit(request: Request) -> None:
    now = time.time()
    ip = _client_ip(request)
    recent = _prune_attempts(ip, now)
    if len(recent) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.")


def register_admin_failed_attempt(request: Request) -> None:
    now = time.time()
    ip = _client_ip(request)
    recent = _prune_attempts(ip, now)
    recent.append(now)
    _failed_attempts[ip] = recent


def clear_admin_failed_attempts(request: Request) -> None:
    ip = _client_ip(request)
    if ip in _failed_attempts:
        del _failed_attempts[ip]


def require_viewer_api(settings: SecuritySettings) -> Callable[[Request], Role]:
    def _dependency(request: Request) -> Role:
        role = get_current_role(request, settings)
        if role in ("viewer", "admin"):
            return role
        raise HTTPException(status_code=401, detail="Authentication required")

    return _dependency


def require_admin_api(settings: SecuritySettings) -> Callable[[Request], Role]:
    def _dependency(request: Request) -> Role:
        role = get_current_role(request, settings)
        if role == "admin":
            return role
        if role is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        raise HTTPException(status_code=403, detail="Admin permission required")

    return _dependency
