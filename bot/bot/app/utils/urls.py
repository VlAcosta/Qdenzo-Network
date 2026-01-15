# -*- coding: utf-8 -*-

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from ..config import settings


def _base_url() -> str:
    return str(settings.public_base_url or settings.marzban_base_url or "").rstrip("/") + "/"


def make_absolute_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url
    base = _base_url()
    if not base:
        return None
    return urljoin(base, url)


def is_http_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)