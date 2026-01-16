# -*- coding: utf-8 -*-

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from ..config import settings

SUPPORTED_INLINE_SCHEMES = {"http", "https", "tg"}

_DEFAULT_PUBLIC_SCHEME = "https"


def _normalize_base_url(url: str | None) -> str:
    if not url:
        return ""
    candidate = str(url).strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme:
        return candidate
    if candidate.startswith("//"):
        return f"{_DEFAULT_PUBLIC_SCHEME}:{candidate}"
    return f"{_DEFAULT_PUBLIC_SCHEME}://{candidate}"



def _base_url() -> str:
    base = _normalize_base_url(settings.public_base_url or settings.marzban_base_url)
    if not base:
        return ""
    return base.rstrip("/") + "/"


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

def build_public_url(path: str) -> str | None:
    base = _base_url()
    if not base:
        return None
    return urljoin(base, path.lstrip("/"))

def is_http_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)



def is_supported_inline_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in SUPPORTED_INLINE_SCHEMES and bool(parsed.netloc)


def sanitize_inline_url(url: str | None) -> str | None:
    absolute = make_absolute_url(url)
    if not absolute:
        return None
    if not is_supported_inline_url(absolute):
        return None
    return absolute