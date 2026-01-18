# -*- coding: utf-8 -*-

from __future__ import annotations

import time
import asyncio
from typing import Any

from loguru import logger
import httpx


class HappCryptoError(RuntimeError):
    pass


_CACHE: dict[str, tuple[float, str]] = {}
_DEFAULT_TTL_SECONDS = 900
_MAX_RETRIES = 2
_RETRY_BACKOFF = 0.6


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


async def encrypt_subscription_url(url: str) -> str | None:
    """
    Happ crypto API: POST https://crypto.happ.su/api.php  JSON {"url": "..."}
    Возвращает зашифрованную ссылку формата happ://crypt3/...
    """
    cached = _cache_get(url)
    if cached:
        return cached
    try:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    r = await c.post("https://crypto.happ.su/api.php", json={"url": url})
                    if r.status_code != 200:
                        raise HappCryptoError(
                            f"Crypto API status {r.status_code}: {r.text[:120]}"
                        )
                    data: Any = r.json()
                # Делает tolerant parsing, т.к. формат ответа может быть {url: "..."} или {result: "..."}
                crypt = (
                    data.get("encrypted_link")
                    or data.get("url")
                    or data.get("result")
                    or data.get("link")
                )
                if not crypt:
                    logger.warning("Happ crypto response missing link payload={}", data)
                    return None
                crypt = str(crypt)
                if not crypt.startswith("happ://"):
                    raise HappCryptoError(f"Crypto API returned unexpected link: {crypt}")
                _cache_set(url, crypt, _DEFAULT_TTL_SECONDS)
                return crypt
            except (httpx.RequestError, ValueError, HappCryptoError) as exc:
                logger.warning("Happ crypto request failed (attempt {}/{}): {}", attempt, _MAX_RETRIES, exc)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF * attempt)
                    continue
                return None
    except Exception as exc:
        logger.exception("Unexpected happ crypto failure: {}", exc)
        return None