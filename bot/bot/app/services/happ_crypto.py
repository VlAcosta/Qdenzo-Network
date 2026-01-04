# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any
import httpx


class HappCryptoError(RuntimeError):
    pass


async def encrypt_subscription_url(url: str) -> str:
    """
    Happ crypto API: POST https://crypto.happ.su/api.php  JSON {"url": "..."}
    Возвращает зашифрованную ссылку формата happ://crypt3/...
    """
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.post("https://crypto.happ.su/api.php", json={"url": url})
        r.raise_for_status()
        data: Any = r.json()

    # Делает tolerant parsing, т.к. формат ответа может быть {url: "..."} или {result: "..."}
    crypt = data.get("url") or data.get("result") or data.get("link")
    if not crypt:
        raise HappCryptoError(f"Crypto API response missing link: {data}")
    return str(crypt)
