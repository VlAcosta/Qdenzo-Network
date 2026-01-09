# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from typing import Any
import httpx


class HappCryptoError(RuntimeError):
    pass
    _CACHE: dict[str, tuple[float, str]] = {}
    _DEFAULT_TTL_SECONDS = 900


    def _cache_get(url: str) -> str | None:
        cached = _CACHE.get(url)
        if not cached:
            return None
        expires_at, value = cached
        if time.monotonic() > expires_at:
            _CACHE.pop(url, None)
            return None
        return value


    def _cache_set(url: str, value: str, ttl_seconds: int) -> None:
        _CACHE[url] = (time.monotonic() + ttl_seconds, value)



async def encrypt_subscription_url(url: str) -> str:
    """
    Happ crypto API: POST https://crypto.happ.su/api.php  JSON {"url": "..."}
    Возвращает зашифрованную ссылку формата happ://crypt3/...
    """
    cached = _cache_get(url)
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.post("https://crypto.happ.su/api.php", json={"url": url})
        r.raise_for_status()
        data: Any = r.json()

    # Делает tolerant parsing, т.к. формат ответа может быть {url: "..."} или {result: "..."}
    crypt = data.get("url") or data.get("result") or data.get("link")
    if not crypt:
        raise HappCryptoError(f"Crypto API response missing link: {data}")
    crypt = str(crypt)
    _cache_set(url, crypt, _DEFAULT_TTL_SECONDS)
    return crypt
