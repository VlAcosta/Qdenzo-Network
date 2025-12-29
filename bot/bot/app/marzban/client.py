# -*- coding: utf-8 -*-

from __future__ import annotations

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
    def __init__(self, *, base_url: str, username: str, password: str, verify_ssl: bool = True, timeout: float = 20.0):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._client = httpx.AsyncClient(base_url=self.base_url, verify=self.verify_ssl, timeout=timeout)
        self._token: Optional[MarzbanAdminToken] = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        # Admin Token endpoint: POST /api/admin/token (OAuth2 password flow)
        data = {
            'username': self.username,
            'password': self.password,
        }
        r = await self._client.post('/api/admin/token', data=data)
        if r.status_code != 200:
            raise MarzbanError(f'Login failed: {r.status_code} {r.text}')
        payload = r.json()
        self._token = MarzbanAdminToken(access_token=payload.get('access_token'), token_type=payload.get('token_type', 'bearer'))

    async def _request(self, method: str, path: str, *, json: Any | None = None, params: Dict[str, Any] | None = None) -> Any:
        if self._token is None:
            await self._login()

        headers = {
            'Authorization': f"{self._token.token_type.title()} {self._token.access_token}",
        }
        r = await self._client.request(method, path, json=json, params=params, headers=headers)
        if r.status_code == 401:
            # retry once
            await self._login()
            headers['Authorization'] = f"{self._token.token_type.title()} {self._token.access_token}"
            r = await self._client.request(method, path, json=json, params=params, headers=headers)

        if r.status_code >= 400:
            raise MarzbanError(f'Marzban API error {r.status_code}: {r.text}')

        # some endpoints can return empty
        if not r.text:
            return None
        try:
            return r.json()
        except Exception:
            return r.text

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._request('GET', f'/api/user/{username}')
        except MarzbanError as e:
            if '404' in str(e):
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
        data_limit_reset_strategy: str = 'no_reset',
        status: str = 'active',
        note: str | None = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            'username': username,
            'status': status,
        }
        # For Marzban: expire is unix timestamp in seconds (0 = unlimited, null = none)
        if expire is not None:
            body['expire'] = int(expire)
        if data_limit is not None:
            body['data_limit'] = int(data_limit)
            body['data_limit_reset_strategy'] = data_limit_reset_strategy
        if inbounds is not None:
            body['inbounds'] = inbounds
        if proxies is not None:
            body['proxies'] = proxies
        if note is not None:
            body['note'] = note

        logger.info(f"Marzban: creating user {username} status={status} expire={expire}")
        return await self._request('POST', '/api/user', json=body)

    async def modify_user(self, username: str, **fields: Any) -> Dict[str, Any]:
        # PUT /api/user/{username}
        return await self._request('PUT', f'/api/user/{username}', json=fields)

    async def remove_user(self, username: str) -> Any:
        return await self._request('DELETE', f'/api/user/{username}')

    async def get_user_usage(self, username: str) -> Dict[str, Any]:
        # GET /api/user/{username}/usage
        return await self._request('GET', f'/api/user/{username}/usage')

    async def revoke_subscription(self, username: str) -> Any:
        # POST /api/user/{username}/revoke_sub
        return await self._request('POST', f'/api/user/{username}/revoke_sub')
