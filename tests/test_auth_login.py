import os
import unittest
from unittest.mock import patch
from hashlib import pbkdf2_hmac
from fastapi.testclient import TestClient

# 테스트 환경에서 시작 실패를 방지하기 위해 main 가져오기 전에 설정을 모킹
os.environ.setdefault("TJ_ENV", "dev")
os.environ.setdefault("TJ_SIGNING_SECRET", "test_signing_secret_at_least_32_bytes_long")
os.environ.setdefault("TJ_VIEWER_TOKEN", "test_viewer_token_dummy_value_123")
os.environ.setdefault("TJ_ADMIN_TOKEN", "test_admin_token_dummy_value_123")
# 테스트 시작 기본값을 위해 PBKDF2 해시를 동적으로 계산하여 주입
from hashlib import pbkdf2_hmac
default_test_hash = pbkdf2_hmac("sha256", b"default_test_password", b"default_salt", 1000).hex()
os.environ.setdefault("TJ_ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$1000$default_salt${default_test_hash}")

from app.config import load_security_settings, SecuritySettings
from app.auth_service import authenticate_admin

class TestAuthLogin(unittest.TestCase):
    def setUp(self):
        self.salt = "test_salt"
        self.iterations = 1000
        self.password = "test_password"
        self.hashed = pbkdf2_hmac("sha256", self.password.encode("utf-8"), self.salt.encode("utf-8"), self.iterations).hex()
        self.mock_hash = f"pbkdf2_sha256${self.iterations}${self.salt}${self.hashed}"

    def test_env_preflight_prod_missing_username_raises_error(self):
        env_mock = {
            "TJ_ENV": "prod",
            "TJ_SIGNING_SECRET": "test_signing_secret_at_least_32_bytes_long",
            "TJ_VIEWER_TOKEN": "test_viewer_token_dummy_value_123",
            "TJ_ADMIN_TOKEN": "test_admin_token_dummy_value_123",
            "TJ_ADMIN_PASSWORD_HASH": self.mock_hash,
        }
        with patch.dict(os.environ, env_mock, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TJ_ADMIN_USERNAME"):
                load_security_settings()

    def test_env_preflight_dev_missing_username_uses_default(self):
        env_mock = {
            "TJ_ENV": "dev",
            "TJ_SIGNING_SECRET": "test_signing_secret_at_least_32_bytes_long",
            "TJ_VIEWER_TOKEN": "test_viewer_token_dummy_value_123",
            "TJ_ADMIN_TOKEN": "test_admin_token_dummy_value_123",
            "TJ_ADMIN_PASSWORD_HASH": self.mock_hash,
        }
        with patch.dict(os.environ, env_mock, clear=True):
            settings = load_security_settings()
            self.assertEqual(settings.admin_username, "admin")

    def test_env_preflight_valid_username_loaded(self):
        env_mock = {
            "TJ_ENV": "prod",
            "TJ_SIGNING_SECRET": "test_signing_secret_at_least_32_bytes_long",
            "TJ_VIEWER_TOKEN": "test_viewer_token_dummy_value_123",
            "TJ_ADMIN_TOKEN": "test_admin_token_dummy_value_123",
            "TJ_ADMIN_PASSWORD_HASH": self.mock_hash,
            "TJ_ADMIN_USERNAME": "super_admin",
        }
        with patch.dict(os.environ, env_mock, clear=True):
            settings = load_security_settings()
            self.assertEqual(settings.admin_username, "super_admin")

    def test_auth_service_admin_success(self):
        settings = SecuritySettings(
            env="dev",
            signing_secret="test_signing_secret_at_least_32_bytes_long",
            viewer_token="test_viewer_token_dummy_value_123",
            admin_token="test_admin_token_dummy_value_123",
            admin_password_hash=self.mock_hash,
            auth_version=1,
            viewer_session_hours=168,
            admin_session_hours=12,
            admin_username="admin"
        )
        self.assertTrue(authenticate_admin("admin", self.password, settings))

    def test_auth_service_admin_invalid_username(self):
        settings = SecuritySettings(
            env="dev",
            signing_secret="test_signing_secret_at_least_32_bytes_long",
            viewer_token="test_viewer_token_dummy_value_123",
            admin_token="test_admin_token_dummy_value_123",
            admin_password_hash=self.mock_hash,
            auth_version=1,
            viewer_session_hours=168,
            admin_session_hours=12,
            admin_username="admin"
        )
        self.assertFalse(authenticate_admin("wrong_admin", self.password, settings))

    def test_auth_service_admin_invalid_password(self):
        settings = SecuritySettings(
            env="dev",
            signing_secret="test_signing_secret_at_least_32_bytes_long",
            viewer_token="test_viewer_token_dummy_value_123",
            admin_token="test_admin_token_dummy_value_123",
            admin_password_hash=self.mock_hash,
            auth_version=1,
            viewer_session_hours=168,
            admin_session_hours=12,
            admin_username="admin"
        )
        self.assertFalse(authenticate_admin("admin", "wrong_password", settings))


class TestAuthLoginRoutes(unittest.TestCase):
    def setUp(self):
        from app.main import app
        self.client = TestClient(app, follow_redirects=False)

    def test_login_page_renders_with_dark_glass_style(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("class=\"page-head\"", response.text)
        self.assertIn("name=\"username\"", response.text)
        self.assertIn("name=\"password\"", response.text)

    def test_login_success_redirects_and_sets_cookie(self):
        from app.main import security_settings
        original_username = security_settings.admin_username
        original_hash = security_settings.admin_password_hash
        
        salt = "route_salt"
        iterations = 1000
        hashed = pbkdf2_hmac("sha256", b"route_password", salt.encode("utf-8"), iterations).hex()
        
        try:
            security_settings.__dict__["admin_username"] = "route_admin"
            security_settings.__dict__["admin_password_hash"] = f"pbkdf2_sha256${iterations}${salt}${hashed}"
            
            response = self.client.post("/login", data={"username": "route_admin", "password": "route_password"})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers.get("location"), "/journal")
            self.assertIn("tj_session", response.cookies)
        finally:
            security_settings.__dict__["admin_username"] = original_username
            security_settings.__dict__["admin_password_hash"] = original_hash

    def test_login_failure_returns_200_with_generic_message(self):
        response = self.client.post("/login", data={"username": "wrong_user", "password": "wrong_password"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("아이디 또는 비밀번호가 올바르지 않습니다.", response.text)

    def test_protected_page_redirects_to_login_for_unauthenticated(self):
        response = self.client.get("/journal")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/login")

    def test_access_page_continues_to_serve_as_fallback_info(self):
        response = self.client.get("/access")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Access Required", response.text)

    def test_access_tokens_fallback_redirects_to_journal(self):
        from app.main import security_settings
        viewer_token = security_settings.viewer_token
        admin_token = security_settings.admin_token
        
        response = self.client.get(f"/access/view/{viewer_token}")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/journal")
        
        response = self.client.get(f"/access/admin/{admin_token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin Unlock", response.text)
