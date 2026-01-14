# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

API_BASE = "https://pay.crypt.bot/api"


@dataclass(slots=True)
class CryptoPayInvoice:
    invoice_id: int
    status: str
    pay_url: str | None
    raw: dict[str, Any]


class CryptoPayError(RuntimeError):
    pass


class CryptoPayClient:
    """Minimal Crypto Pay API client (create/get invoices)."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = API_BASE,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.6,
    ) -> None:
        self._token = token
        self._api_base = api_base
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Crypto-Pay-API-Token": self._token}
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self._api_base, timeout=self._timeout) as client:
                    response = await client.post(f"/{method}", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise CryptoPayError(f"CryptoPay {method} failed: {data}")
                return data.get("result", {})
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status >= 500 and attempt < self._max_retries:
                    logger.warning("CryptoPay %s failed (%s). Retrying...", method, status)
                    await asyncio.sleep(self._backoff_base * attempt)
                    continue
                raise
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("CryptoPay request error (%s/%s): %s", attempt, self._max_retries, exc)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_base * attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise CryptoPayError("CryptoPay request failed without response")

    async def create_invoice(
        self,
        *,
        amount: str,
        asset: str,
        description: str,
        payload: str,
        expires_in: int | None = None,
    ) -> CryptoPayInvoice:
        req: dict[str, Any] = {
            "amount": amount,
            "asset": asset,
            "description": description,
            "payload": payload,
        }
        if expires_in:
            req["expires_in"] = int(expires_in)
        result = await self._request(
            "createInvoice",
            req,
        )
        logger.info("CryptoPay invoice created amount={} asset={}", amount, asset)
        return CryptoPayInvoice(
            invoice_id=int(result["invoice_id"]),
            status=str(result.get("status", "")),
            pay_url=result.get("pay_url"),
            raw=result,
        )

    async def get_invoice(self, invoice_id: int) -> CryptoPayInvoice | None:
        result = await self._request("getInvoices", {"invoice_ids": [invoice_id]})
        items = result.get("items") or result.get("invoices") or []
        if not items:
            return None
        invoice = items[0]
        return CryptoPayInvoice(
            invoice_id=int(invoice.get("invoice_id")),
            status=str(invoice.get("status", "")),
            pay_url=invoice.get("pay_url"),
            raw=invoice,
        )

    async def get_exchange_rates(self) -> list[dict[str, Any]]:
        result = await self._request("getExchangeRates", {})
        return list(result or [])


def verify_webhook_signature(*, token: str, body: bytes, signature: str | None) -> bool:
    """Verify Crypto Pay webhook signature (HMAC SHA-256)."""
    if not signature:
        return False
    digest = hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def is_paid_status(status: str) -> bool:
    return status in {"paid", "confirmed", "paid_confirmed"}