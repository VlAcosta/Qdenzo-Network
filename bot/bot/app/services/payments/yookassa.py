from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from loguru import logger

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

    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        *,
        api_base: str = API_BASE,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.6,
    ) -> None:
        self._shop_id = shop_id
        self._secret_key = secret_key
        self._api_base = api_base
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

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
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self._api_base, timeout=self._timeout, auth=auth) as client:
                    response = await client.request(method, url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status >= 500 and attempt < self._max_retries:
                    logger.warning("YooKassa %s %s failed (%s). Retrying...", method, url, status)
                    await asyncio.sleep(self._backoff_base * attempt)
                    continue
                raise
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("YooKassa request error (%s/%s): %s", attempt, self._max_retries, exc)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_base * attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise YooKassaError("YooKassa request failed without response")

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
        logger.info("YooKassa payment created amount={} description={}", amount_rub, description)
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