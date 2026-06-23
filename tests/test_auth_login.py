import os
import unittest
from unittest.mock import patch

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
