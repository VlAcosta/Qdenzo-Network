# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

import hashlib
import httpx


class HappProxyError(RuntimeError):
    pass


@dataclass(frozen=True)
class HappProxyConfig:
    api_base: str
    provider_code: str
    auth_key: str


def _with_install_id(url: str, install_code: str) -> str:
    """
    Добавляем InstallID=install_code к подписке (сохраняем все остальные query-параметры).
    """
    u = urlparse(url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q["InstallID"] = install_code
    new_query = urlencode(q, doseq=True)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))


def _domain_hash(url: str) -> str:
    """
    SHA-256 домена (lowercase hex), как требует Happ-Proxy.
    """
    u = urlparse(url)
    domain = (u.hostname or "").lower()
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()


async def add_install_code(cfg: HappProxyConfig, *, install_limit: int, note: Optional[str] = None) -> str:
    """
    GET /api/add-install?provider_code=...&auth_key=...&install_limit=...
    Возвращает install_code.
    """
    if install_limit < 1 or install_limit > 100:
        raise HappProxyError("install_limit must be 1..100")

    params: dict[str, Any] = {
        "provider_code": cfg.provider_code,
        "auth_key": cfg.auth_key,
        "install_limit": int(install_limit),
    }
    if note:
        params["note"] = note[:255]

    async with httpx.AsyncClient(base_url=cfg.api_base, timeout=15, follow_redirects=True) as c:
        r = await c.get("/api/add-install", params=params)
        r.raise_for_status()
        data = r.json()

    # По докам бизнес-статус приходит в rc/msg, при успехе — success+install_code
    # (точные поля могут отличаться, поэтому делаем tolerant parsing).
    rc = data.get("rc")
    if rc not in (0, "0", None) and str(rc) != "0":
        raise HappProxyError(f"add-install failed: rc={rc}, msg={data.get('msg')}, data={data}")

    install_code = data.get("install_code") or data.get("installID") or data.get("InstallID")
    if not install_code:
        raise HappProxyError(f"install_code missing in response: {data}")
    return str(install_code)


async def add_domain_if_needed(cfg: HappProxyConfig, subscription_url: str, domain_name: Optional[str] = None) -> None:
    """
    Опционально: привязать домен подписки. Обычно он добавляется автоматически при создании лимитированной ссылки,
    но оставляем функцию на будущее.
    GET /api/add-domain?provider_code=...&auth_key=...&domain_hash=...
    """
    params: dict[str, Any] = {
        "provider_code": cfg.provider_code,
        "auth_key": cfg.auth_key,
        "domain_hash": _domain_hash(subscription_url),
    }
    if domain_name:
        params["domain_name"] = domain_name

    async with httpx.AsyncClient(base_url=cfg.api_base, timeout=15, follow_redirects=True) as c:
        r = await c.get("/api/add-domain", params=params)
        # даже если домен уже был — это не ошибка для нашего сценария
        r.raise_for_status()
