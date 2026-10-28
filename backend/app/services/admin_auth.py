"""Password hashing and signed bearer sessions for the knowledge admin."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.core.config import settings

TOKEN_TTL_SECONDS = 8 * 60 * 60
SCRYPT_N = 1 << 14


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=8, p=1, dklen=64)
    return f"scrypt${SCRYPT_N}$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (SCRYPT_N, 8, 1):
            return False
        expected = _unb64(digest_text)
        salt = _unb64(salt_text)
        if len(expected) != 64 or len(salt) != 16:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _signing_key() -> bytes:
    secret = settings.supabase_service_key.strip()
    if not secret:
        raise RuntimeError("Admin authentication requires the server-side Supabase service key.")
    return hashlib.sha256(b"we3vision-admin-session-v1:" + secret.encode("utf-8")).digest()


def issue_token(admin: dict[str, Any]) -> tuple[str, int]:
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = _b64(json.dumps({
        "sub": str(admin["id"]),
        "email": str(admin["email"]),
        "exp": expires_at,
    }, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}", TOKEN_TTL_SECONDS


def verify_token(token: str) -> dict[str, str] | None:
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
        claims = json.loads(_unb64(payload))
        if not isinstance(claims, dict) or int(claims.get("exp", 0)) <= int(time.time()):
            return None
        if not claims.get("sub") or not claims.get("email"):
            return None
        return {"id": str(claims["sub"]), "email": str(claims["email"])}
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError, RuntimeError):
        return None


def supabase_admin_client():
    from supabase import create_client

    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Admin login requires SUPABASE_URL and SUPABASE_SERVICE_KEY on the backend.")
    return create_client(settings.supabase_url, settings.supabase_service_key)
