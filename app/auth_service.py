from app.config import SecuritySettings
from app.security import verify_admin_password
import hmac

def authenticate_admin(username: str, password: str, settings: SecuritySettings) -> bool:
    if not hmac.compare_digest(username, settings.admin_username):
        return False
    return verify_admin_password(password, settings)
