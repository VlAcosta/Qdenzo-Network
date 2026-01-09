# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

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

    def __init__(self, token: str, *, api_base: str = API_BASE, timeout: float = 10.0) -> None:
        self._token = token
        self._api_base = api_base
        self._timeout = timeout

    async def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Crypto-Pay-API-Token": self._token}
        async with httpx.AsyncClient(base_url=self._api_base, timeout=self._timeout) as client:
            response = await client.post(f"/{method}", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise CryptoPayError(f"CryptoPay {method} failed: {data}")
        return data.get("result", {})

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