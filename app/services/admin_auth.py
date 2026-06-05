"""Lightweight HMAC-signed admin tokens (no external JWT dep needed)."""
import base64
import hmac
import hashlib
import json
import secrets
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings


security = HTTPBearer(auto_error=False)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(payload: bytes) -> str:
    sig = hmac.new(
        settings.ADMIN_JWT_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    return _b64(sig)


def issue_token(username: str) -> tuple[str, int]:
    expires_at = int(time.time()) + settings.ADMIN_TOKEN_EXPIRE_HOURS * 3600
    payload = {"sub": username, "exp": expires_at, "jti": secrets.token_hex(8)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = _b64(raw)
    sig = _sign(body.encode("ascii"))
    return f"{body}.{sig}", expires_at


def verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = _sign(body.encode("ascii"))
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def verify_credentials(username: str, password: str) -> bool:
    submitted_username = username.strip().casefold()
    configured_username = settings.ADMIN_USERNAME.strip().casefold()
    submitted_password = password.strip()
    configured_password = settings.ADMIN_PASSWORD.strip()

    return hmac.compare_digest(
        submitted_username, configured_username
    ) and hmac.compare_digest(
        submitted_password, configured_password
    )


def require_admin(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(creds.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
