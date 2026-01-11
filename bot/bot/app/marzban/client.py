# -*- coding: utf-8 -*-

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from loguru import logger


@dataclass
class MarzbanAdminToken:
    access_token: str
    token_type: str


class MarzbanError(RuntimeError):
    pass


class MarzbanClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=self.verify_ssl,
            timeout=timeout,
            follow_redirects=True,
        )
        self._token: Optional[MarzbanAdminToken] = None

        # если base_url уже заканчивается на /api, не добавляем /api второй раз
        self.api_prefix = "" if self.base_url.endswith("/api") else "/api"

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        data = {"username": self.username, "password": self.password}

        # некоторые инсталлы требуют trailing slash
        endpoints = [
            f"{self.api_prefix}/admin/token",
            f"{self.api_prefix}/admin/token/",
        ]

        last = None
        for ep in endpoints:
            r = await self._client.post(ep, data=data)
            if r.status_code == 200:
                payload = r.json()
                self._token = MarzbanAdminToken(
                    access_token=payload.get("access_token"),
                    token_type=payload.get("token_type", "bearer"),
                )
                return
            last = r

        raise MarzbanError(f"Login failed: {last.status_code} {last.text}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Dict[str, Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            if self._token is None:
                await self._login()

            headers = {"Authorization": f"{self._token.token_type.title()} {self._token.access_token}"}
            try:
                r = await self._client.request(method, path, json=json, params=params, headers=headers)
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("Marzban request error (attempt %s/%s): %s", attempt, self.max_retries, exc)
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if r.status_code in {401, 403}:
                if attempt == self.max_retries:
                    raise MarzbanError(f"Marzban auth error {r.status_code}: {r.text}")
                await self._login()
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if r.status_code >= 500:
                last_error = MarzbanError(f"Marzban API error {r.status_code}: {r.text}")
                logger.warning("Marzban temporary error (attempt %s/%s): %s", attempt, self.max_retries, last_error)
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if r.status_code >= 400:
                raise MarzbanError(f"Marzban API error {r.status_code}: {r.text}")

            if not r.text:
                return None
            try:
                return r.json()
            except Exception:
                return r.text

        if last_error:
            raise MarzbanError(f"Marzban request failed after retries: {last_error}")
        raise MarzbanError("Marzban request failed after retries")


    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._request("GET", f"{self.api_prefix}/user/{username}")
        except MarzbanError as e:
            if "404" in str(e):
                return None
            raise

    async def create_user(
        self,
        *,
        username: str,
        expire: int | None,
        inbounds: Dict[str, list[str]] | None = None,
        proxies: Dict[str, dict] | None = None,
        data_limit: int | None = None,
        data_limit_reset_strategy: str = "no_reset",
        status: str = "active",
        note: str | None = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"username": username, "status": status}

        if expire is not None:
            body["expire"] = int(expire)
        if data_limit is not None:
            body["data_limit"] = int(data_limit)
            body["data_limit_reset_strategy"] = data_limit_reset_strategy
        if inbounds is not None:
            body["inbounds"] = inbounds
        if proxies is not None:
            body["proxies"] = proxies
        if note is not None:
            body["note"] = note

        logger.info(f"Marzban: creating user {username} status={status} expire={expire}")
        return await self._request("POST", f"{self.api_prefix}/user", json=body)

    async def modify_user(self, username: str, **fields: Any) -> Dict[str, Any]:
        return await self._request("PUT", f"{self.api_prefix}/user/{username}", json=fields)
    
    async def update_user(self, username: str, **fields: Any) -> Dict[str, Any]:
        return await self.modify_user(username, **fields)


    async def remove_user(self, username: str) -> Any:
        return await self._request("DELETE", f"{self.api_prefix}/user/{username}")

    async def get_user_usage(self, username: str) -> Dict[str, Any]:
        return await self._request("GET", f"{self.api_prefix}/user/{username}/usage")

    async def revoke_subscription(self, username: str) -> Any:
        return await self._request("POST", f"{self.api_prefix}/user/{username}/revoke_sub")
