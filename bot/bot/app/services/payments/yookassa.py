from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

API_BASE = "https://api.yookassa.ru/v3"


@dataclass(slots=True)
class YooKassaPayment:
    payment_id: str
    status: str
    confirmation_url: str | None
    raw: dict[str, Any]


class YooKassaError(RuntimeError):
    pass


class YooKassaClient:
    """Minimal YooKassa API client (create/get payments)."""

    def __init__(self, shop_id: str, secret_key: str, *, api_base: str = API_BASE, timeout: float = 10.0) -> None:
        self._shop_id = shop_id
        self._secret_key = secret_key
        self._api_base = api_base
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotence_key: str | None = None,
    ) -> dict[str, Any]:
        auth = (self._shop_id, self._secret_key)
        headers = {}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key
        async with httpx.AsyncClient(base_url=self._api_base, timeout=self._timeout, auth=auth) as client:
            response = await client.request(method, url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    async def create_payment(
        self,
        *,
        amount_rub: int,
        description: str,
        return_url: str,
        metadata: dict[str, Any],
        idempotence_key: str | None = None,
    ) -> YooKassaPayment:
        payload = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description,
            "metadata": metadata,
        }
        result = await self._request("POST", "/payments", payload, idempotence_key=idempotence_key or str(uuid4()))
        confirmation_url = result.get("confirmation", {}).get("confirmation_url")
        return YooKassaPayment(
            payment_id=str(result["id"]),
            status=str(result.get("status", "")),
            confirmation_url=confirmation_url,
            raw=result,
        )

    async def get_payment(self, payment_id: str) -> YooKassaPayment:
        result = await self._request("GET", f"/payments/{payment_id}")
        confirmation_url = result.get("confirmation", {}).get("confirmation_url")
        return YooKassaPayment(
            payment_id=str(result["id"]),
            status=str(result.get("status", "")),
            confirmation_url=confirmation_url,
            raw=result,
        )


def is_paid_status(status: str) -> bool:
    return status in {"succeeded"}