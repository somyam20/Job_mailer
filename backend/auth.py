import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, HTTPException
from sqlalchemy import delete

from .db import DATA_DIR, ON_VERCEL, AuthSession, SessionLocal, User

SESSION_DAYS = 30
COOKIE = "jm_session"


# ---------- passwords ----------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(test.hex(), digest)


# ---------- sessions ----------
def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with SessionLocal() as s:
        s.execute(delete(AuthSession).where(AuthSession.expires_at < datetime.now()))
        s.add(AuthSession(token=token, user_id=user_id, expires_at=datetime.now() + timedelta(days=SESSION_DAYS)))
        s.commit()
    return token


def end_session(token: str | None):
    if token:
        with SessionLocal() as s:
            s.execute(delete(AuthSession).where(AuthSession.token == token))
            s.commit()


def current_user(jm_session: str | None = Cookie(default=None)) -> User:
    """FastAPI dependency: the logged-in user, or 401."""
    if jm_session:
        with SessionLocal() as s:
            sess = s.get(AuthSession, jm_session)
            if sess and sess.expires_at > datetime.now():
                user = s.get(User, sess.user_id)
                if user:
                    return user
    raise HTTPException(401, "Please log in")


# ---------- encryption for stored secrets (SMTP password, Gemini key) ----------
def _fernet() -> Fernet:
    key = os.getenv("APP_SECRET_KEY")
    if not key and ON_VERCEL:
        # each serverless instance would invent its own key and could never read the others' secrets
        raise HTTPException(500, "Server misconfigured: set APP_SECRET_KEY in the Vercel environment variables")
    if not key:
        path = DATA_DIR / "secret.key"
        if not path.exists():
            path.write_bytes(Fernet.generate_key())
        key = path.read_bytes().decode()
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode() if value else ""
    except InvalidToken:
        return ""
