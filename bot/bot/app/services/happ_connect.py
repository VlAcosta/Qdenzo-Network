# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from typing import Final

from loguru import logger

from .happ_crypto import encrypt_subscription_url


_CACHE_TTL_SECONDS: Final[int] = 900
_CACHE: dict[str, tuple[float, tuple[str, str | None]]] = {}


def _cache_get(url: str) -> tuple[str, str | None] | None:
    cached = _CACHE.get(url)
    if not cached:
        return None
    expires_at, value = cached
    if time.monotonic() > expires_at:
        _CACHE.pop(url, None)
        return None
    return value


def _cache_set(url: str, value: tuple[str, str | None], ttl_seconds: int) -> None:
    _CACHE[url] = (time.monotonic() + ttl_seconds, value)


async def build_happ_links(plain_url: str) -> tuple[str, str | None]:
    """Return (plain_url, crypt_url) for Happ deep link import."""
    cached = _cache_get(plain_url)
    if cached:
        return cached

    crypt_url = None
    try:
        crypt_url = await encrypt_subscription_url(plain_url)
    except Exception as exc:
        logger.exception("Happ encryption failed for {}: {}", plain_url, exc)

    if not crypt_url:
        logger.warning("Happ encryption unavailable, falling back to plain link for {}", plain_url)
        
    result = (plain_url, crypt_url)
    _cache_set(plain_url, result, _CACHE_TTL_SECONDS)
    return result