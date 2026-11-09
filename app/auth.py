"""Sign-in: one account, a signed cookie that lasts a year so she stays signed in on her device.

Credentials come from [auth] in settings.toml, overridden by SPELLING_USERNAME / SPELLING_PASSWORD.
The cookie is signed with SPELLING_SECRET_KEY, or a random key saved in the data folder.
SPELLING_AUTH=off turns sign-in off (the tests use this).
"""
import hashlib
import hmac
import os
import secrets
import time

from .config import DATA_DIR

COOKIE = "spelling_session"
MAX_AGE = 365 * 24 * 3600
# Paths anyone can load: the sign-in page itself and the app's code/styles/icons.
OPEN = ("/login", "/api/login", "/static/", "/manifest.webmanifest", "/favicon.ico")


def enabled() -> bool:
    return os.environ.get("SPELLING_AUTH", "on").lower() != "off"


def credentials(settings: dict) -> tuple[str, str]:
    cfg = settings.get("auth", {})
    return (os.environ.get("SPELLING_USERNAME", cfg.get("username", "")),
            os.environ.get("SPELLING_PASSWORD", cfg.get("password", "")))


def _secret() -> bytes:
    if key := os.environ.get("SPELLING_SECRET_KEY"):
        return key.encode()
    path = DATA_DIR / "secret_key"
    if not path.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip().encode()


def check_password(settings: dict, username: str, password: str) -> bool:
    user, pw = credentials(settings)
    # Username ignores case ("lexi" works); the password must match exactly.
    return bool(user and pw) and hmac.compare_digest(username.strip().lower(), user.lower()) \
        and hmac.compare_digest(password, pw)


def make_cookie(username: str) -> str:
    payload = f"{username.strip().lower()}|{int(time.time())}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def valid_cookie(value: str | None, settings: dict) -> bool:
    try:
        user, issued, sig = (value or "").rsplit("|", 2)
    except ValueError:
        return False
    good = hmac.new(_secret(), f"{user}|{issued}".encode(), hashlib.sha256).hexdigest()
    return (hmac.compare_digest(sig, good) and user == credentials(settings)[0].lower()
            and time.time() - int(issued) < MAX_AGE)


def is_open(path: str) -> bool:
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in OPEN)
