# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from typing import NamedTuple

from ..config import settings


class ConnectToken(NamedTuple):
    device_id: int
    user_id: int
    expires_at: int


def _secret() -> bytes:
    return settings.bot_token.encode("utf-8")


def create_connect_token(*, device_id: int, user_id: int, ttl_seconds: int = 900) -> str:
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{device_id}:{user_id}:{expires_at}".encode("utf-8")
    signature = hmac.new(_secret(), payload, sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    return f"{token}.{signature}"


def verify_connect_token(token: str) -> ConnectToken | None:
    if not token or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("utf-8"))
        expected = hmac.new(_secret(), payload, sha256).hexdigest()
    except Exception:
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        device_id_s, user_id_s, expires_at_s = payload.decode("utf-8").split(":", 2)
        expires_at = int(expires_at_s)
    except Exception:
        return None
    if int(time.time()) > expires_at:
        return None
    return ConnectToken(device_id=int(device_id_s), user_id=int(user_id_s), expires_at=expires_at)