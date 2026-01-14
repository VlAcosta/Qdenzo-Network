# -*- coding: utf-8 -*-


import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from loguru import logger


@dataclass
class MarzbanAdminToken:
    access_token: str
    token_type: str = "bearer"


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
        api_prefix: str | None = None,
        # Дефолты (можно потом подтянуть из env/settings)
        default_inbounds: Optional[Dict[str, list[str]]] = None,
        default_proxies: Optional[Dict[str, dict]] = None,
    ):
        self.base_url = self._normalize_base_url(base_url)
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=self.verify_ssl,
            timeout=timeout,
            follow_redirects=True,
        )
        self._token: Optional[MarzbanAdminToken] = None
        self._diag_logged = False
        self._inbounds_cache: Dict[str, list[str]] | None = None

        # api_prefix normalization
        if api_prefix is None:
            api_prefix = "/api"
        if api_prefix == "/":
            api_prefix = ""
        if api_prefix and not api_prefix.startswith("/"):
            api_prefix = f"/{api_prefix}"
        self.api_prefix = api_prefix

        # Твои реальные дефолты по Xray config:
        # inbound tag = vless-reality, protocol = vless
        self.default_inbounds = default_inbounds or {"vless": ["vless-reality"]}
        self.default_proxies = default_proxies or {"vless": {"flow": "xtls-rprx-vision"}}

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[:-4].rstrip("/")
        if not normalized:
            return base_url
        return normalized

    async def _login(self) -> None:
        """
        Логин: некоторые установки Marzban отличаются путём и наличием trailing slash.
        ВАЖНО: 404/405 — это "попробуй другой endpoint", а не фатальная ошибка.
        """
        data = {"username": self.username, "password": self.password}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        endpoints = [
            # ТВОЙ рабочий endpoint (по curl)
            f"{self.api_prefix}/admin/token",
            # fallback
            f"{self.api_prefix}/admin/token/",
            f"{self.api_prefix}/token",
            f"{self.api_prefix}/token/",
        ]

        logger.info(
            "Marzban login start base_url={} api_prefix={} endpoints={}",
            self.base_url,
            self.api_prefix,
            endpoints,
        )


        last_status: Optional[int] = None
        last_body: str = ""

        for ep in endpoints:
            try:
                r = await self._client.post(ep, data=data, headers=headers)
            except httpx.RequestError as exc:
                last_status = None
                last_body = str(exc)
                logger.warning("Marzban login request error endpoint={} err={}", ep, exc)
                continue

            if r.status_code == 200:
                payload = r.json()
                access_token = payload.get("access_token")
                token_type = payload.get("token_type", "bearer") or "bearer"
                if not access_token:
                    raise MarzbanError("Login OK but access_token missing in response")
                self._token = MarzbanAdminToken(access_token=access_token, token_type=token_type)
                logger.info("Marzban login OK via {}", ep)
                return

            last_status = r.status_code
            last_body = (r.text or "")[:300]

            # 404/405 — пробуем следующий endpoint
            if r.status_code in {404, 405}:
                logger.debug(
                    "Marzban login endpoint not found endpoint={} status={} body={}",
                    ep,
                    r.status_code,
                    last_body,
                )
                continue
            
            if r.status_code in {307, 308}:
                logger.info("Marzban login redirect endpoint={} status={} location={}", ep, r.status_code, r.headers.get("location"))
                continue

            # 401 — фатально (неправильные креды)
            if r.status_code in {401, 403}:
                logger.error("Marzban login forbidden endpoint={} status={} body={}", ep, r.status_code, last_body)
                raise MarzbanError(f"Login failed: {r.status_code} {r.text}")

            # прочие статусы тоже считаем фатальными
            logger.error("Marzban login failed endpoint={} status={} body={}", ep, r.status_code, last_body)
            raise MarzbanError(f"Login failed: {r.status_code} {r.text}")

        # если дошли сюда — ни один endpoint не сработал
        logger.error("Marzban login failed after trying all endpoints last_status={} last_body={}", last_status, last_body)
        raise MarzbanError(f"Login failed: {last_status} {last_body}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Dict[str, Any] | None = None,
        data: Any | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        method_u = method.upper()

        for attempt in range(1, self.max_retries + 1):
            if self._token is None:
                await self._login()

            req_headers = dict(headers or {})
            # ВАЖНО: явно Bearer
            req_headers["Authorization"] = f"Bearer {self._token.access_token}"

            try:
                r = await self._client.request(
                    method_u,
                    path,
                    json=json,
                    params=params,
                    data=data,
                    headers=req_headers,
                )
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "Marzban request error attempt={}/{} method={} path={} err={}",
                    attempt,
                    self.max_retries,
                    method_u,
                    path,
                    exc,
                )
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if not self._diag_logged:
                self._diag_logged = True
                logger.info(
                    "Marzban diag base_url={} api_prefix={} endpoint={} status={}",
                    self.base_url,
                    self.api_prefix,
                    str(r.request.url),
                    r.status_code,
                )

            if r.status_code in {401, 403}:
                last_error = MarzbanError(f"Auth error {r.status_code}: {r.text}")
                logger.warning(
                    "Marzban auth error attempt={}/{} method={} path={} status={} body={}",
                    attempt,
                    self.max_retries,
                    method_u,
                    path,
                    r.status_code,
                    (r.text or "")[:200],
                )
                if attempt == self.max_retries:
                    raise MarzbanError(f"Marzban auth error {r.status_code}: {r.text}")
                self._token = None
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if r.status_code >= 500:
                last_error = MarzbanError(f"Marzban API error {r.status_code}: {r.text}")
                logger.warning(
                    "Marzban temporary error attempt={}/{} method={} path={} status={} body={}",
                    attempt,
                    self.max_retries,
                    method_u,
                    path,
                    r.status_code,
                    (r.text or "")[:200],
                )
                await asyncio.sleep(self.backoff_base * attempt)
                continue

            if r.status_code >= 400:
                logger.warning(
                    "Marzban API error method={} path={} status={} body={}",
                    method_u,
                    path,
                    r.status_code,
                    (r.text or "")[:200],
                )
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

    # -------- USERS --------

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Осторожно: у тебя endpoint /api/user/{username} может 500, если у юзера proxies=[]
        """
        try:
            user = await self._request("GET", f"{self.api_prefix}/user/{username}")
        except MarzbanError as e:
            s = str(e)
            if "error 404" in s.lower() or " 404" in s:
                return None
            raise

        if isinstance(user, dict) and not user.get("proxies"):
            try:
                inbounds, proxies = await self._resolve_inbounds_proxies()
                if proxies:
                    logger.warning("Marzban user {} returned empty proxies, patching defaults", username)
                    updated = await self.update_user(username, inbounds=inbounds, proxies=proxies)
                    if isinstance(updated, dict):
                        user = updated
            except Exception as exc:
                logger.warning("Marzban user {} proxies patch failed: {}", username, exc)
        return user

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

    async def get_system_info(self) -> Dict[str, Any] | None:
        try:
            return await self._request("GET", f"{self.api_prefix}/system")
        except MarzbanError as exc:
            if "404" in str(exc):
                return None
            raise

    async def list_inbounds(self) -> Dict[str, list[str]] | None:
        try:
            data = await self._request("GET", f"{self.api_prefix}/inbounds")
        except MarzbanError as exc:
            if "404" in str(exc):
                return None
            raise
        items = None
        if isinstance(data, dict):
            items = data.get("inbounds") or data.get("items")
        elif isinstance(data, list):
            items = data
        if not isinstance(items, list):
            return None
        resolved: Dict[str, list[str]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag") or item.get("name")
            protocol = item.get("protocol") or item.get("type")
            if not tag or not protocol:
                continue
            resolved.setdefault(str(protocol), []).append(str(tag))
        if resolved:
            self._inbounds_cache = resolved
            return resolved
        return None

    async def _resolve_inbounds_proxies(self) -> tuple[Dict[str, list[str]], Dict[str, dict]]:
        if self._inbounds_cache is None:
            try:
                await self.list_inbounds()
            except MarzbanError as exc:
                logger.warning("Marzban inbounds lookup failed: {}", exc)
        inbounds = self._inbounds_cache or self.default_inbounds
        proxies = self.default_proxies
        return inbounds, proxies

    # -------- CREATE USER (CRITICAL) --------

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
        """
        КРИТИЧНО:
        Всегда задаём inbounds/proxies, чтобы Marzban не создавал пользователя с proxies=[]
        """

        if inbounds is None or proxies is None:
            resolved_inbounds, resolved_proxies = await self._resolve_inbounds_proxies()
            if inbounds is None:
                inbounds = resolved_inbounds
            if proxies is None:
                proxies = resolved_proxies

        body: Dict[str, Any] = {
            "username": username,
            "status": status,
            "inbounds": inbounds,
            "proxies": proxies,
        }

        if expire is not None:
            body["expire"] = int(expire)

        if data_limit is not None:
            body["data_limit"] = int(data_limit)
            body["data_limit_reset_strategy"] = data_limit_reset_strategy

        if note is not None:
            body["note"] = note

        logger.info("Marzban: creating user={} status={} expire={}", username, status, expire)

        try:
            return await self._request("POST", f"{self.api_prefix}/user", json=body)
        except MarzbanError as exc:
            msg = str(exc).lower()

            # 409 exists — не дергаем get_user(), делаем идемпотентность
            if "409" in msg and ("exist" in msg or "already" in msg):
                logger.info("Marzban: user already exists, reusing username={}", username)
                try:
                    if inbounds and proxies:
                        await self.update_user(username, inbounds=inbounds, proxies=proxies)
                except Exception as upd_exc:
                    logger.warning("Marzban: user update after 409 failed for {}: {}", username, upd_exc)
                return {"username": username}

            raise
