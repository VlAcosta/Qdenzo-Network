from __future__ import annotations

import asyncio
import json
import html
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import select

from .config import settings
from .db import session_scope
from .marzban.client import MarzbanClient
from .models import Device, Order
from .services.orders import get_order, mark_order_paid
from .services.happ_connect import build_happ_links
from .services.payments import (
    CryptoPayClient,
    YooKassaClient,
    is_cryptopay_paid,
    is_yookassa_paid,
)
from .services.payments.cryptopay import verify_webhook_signature
from .utils.connect import verify_connect_token
from .utils.urls import make_absolute_url

def _marzban_client() -> MarzbanClient:
    return MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
        default_inbounds={settings.marzban_proxy_type: [settings.marzban_inbound_tag]},
        default_proxies={settings.marzban_proxy_type: {"flow": settings.reality_flow}},
    )


async def _process_paid_order(
    order_id: int | None,
    *,
    provider: str,
    provider_id: str | int | None,
    raw_payload: dict[str, Any] | None = None,
) -> None:
    async with session_scope() as session:
        order = None
        if order_id:
            order = await get_order(session, order_id)
        elif provider_id:
            q = await session.execute(
                select(Order).where(Order.provider_payment_id == str(provider_id))
            )
            order = q.scalar_one_or_none()
        if not order:
            logger.warning("Webhook: order %s not found for %s", order_id, provider)
            return
        if order.status != "pending":
            logger.info("Webhook: order %s already processed", order_id)
            return

        if order.provider and order.provider not in {provider, "manual"}:
            logger.warning("Webhook: provider mismatch for order %s", order_id)
            return
        if provider_id and order.provider_payment_id and str(order.provider_payment_id) != str(provider_id):
            logger.warning("Webhook: provider id mismatch for order %s", order_id)
            return
        
        if provider == "yookassa" and raw_payload:
            amount = raw_payload.get("amount") or {}
            if amount.get("currency") and amount.get("currency") != "RUB":
                logger.warning("Webhook: currency mismatch for order %s", order_id)
                return
            if order.amount_rub:
                expected = f"{order.amount_rub:.2f}"
                if str(amount.get("value")) != expected:
                    logger.warning("Webhook: amount mismatch for order %s", order_id)
                    return
            metadata = raw_payload.get("metadata") or {}
            if metadata.get("order_id") and str(metadata.get("order_id")) != str(order.id):
                logger.warning("Webhook: metadata order mismatch for order %s", order_id)
                return
        if provider == "cryptopay" and raw_payload:
            if order.currency and raw_payload.get("asset") and raw_payload.get("asset") != order.currency:
                logger.warning("Webhook: asset mismatch for order %s", order_id)
                return
            if order.amount and raw_payload.get("amount") and str(raw_payload.get("amount")) != str(order.amount):
                logger.warning("Webhook: amount mismatch for order %s", order_id)
                return
            payload_raw = raw_payload.get("payload")
            if payload_raw:
                try:
                    payload = json.loads(payload_raw)
                    if payload.get("order_id") and str(payload.get("order_id")) != str(order.id):
                        logger.warning("Webhook: payload order mismatch for order %s", order_id)
                        return
                except Exception:
                    logger.warning("Webhook: payload parse failed for order %s", order_id)

        order.provider = provider
        if provider_id:
            order.provider_payment_id = str(provider_id)
        if raw_payload:
            order.raw_provider_payload = json.dumps(raw_payload, ensure_ascii=False)
        session.add(order)
        await session.commit()

        marz = _marzban_client()
        try:
            await mark_order_paid(session=session, marz=marz, order=order)
        finally:
            await marz.close()


async def _handle_cryptopay(invoice_id: int | None, payload_raw: str | None) -> None:
    cryptopay_token = getattr(settings, "cryptopay_token", None)
    if not cryptopay_token or not invoice_id:
        return

    order_id = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            order_id = int(payload.get("order_id"))
        except Exception:
            order_id = None

    client = CryptoPayClient(cryptopay_token)
    try:
        invoice = await client.get_invoice(int(invoice_id))
    except Exception as exc:
        logger.exception("CryptoPay webhook: failed to fetch invoice %s: %s", invoice_id, exc)
        return
    if not invoice or not is_cryptopay_paid(invoice.status):
        return

    await _process_paid_order(
        order_id,
        provider="cryptopay",
        provider_id=invoice_id,
        raw_payload=invoice.raw,
    )

async def _handle_yookassa(payment_id: str | None, metadata: dict[str, Any] | None) -> None:
    shop_id = getattr(settings, "yookassa_shop_id", None)
    secret_key = getattr(settings, "yookassa_secret_key", None)
    if not (shop_id and secret_key and payment_id):
        return

    order_id = None
    if metadata:
        try:
            order_id = int(metadata.get("order_id"))
        except Exception:
            order_id = None

    client = YooKassaClient(shop_id, secret_key)
    try:
        payment = await client.get_payment(payment_id)
    except Exception as exc:
        logger.exception("YooKassa webhook: failed to fetch payment %s: %s", payment_id, exc)
        return
    if not is_yookassa_paid(payment.status):
        return

    await _process_paid_order(
        order_id,
        provider="yookassa",
        provider_id=payment_id,
        raw_payload=payment.raw,
    )


async def cryptopay_webhook(request: web.Request) -> web.Response:
    secret = request.match_info.get("secret")
    webhook_path_secret = getattr(settings, "cryptopay_webhook_path_secret", None)
    webhook_secret = getattr(settings, "cryptopay_webhook_secret", None)
    if webhook_path_secret and secret != webhook_path_secret:
        return web.Response(status=404)

    body = await request.read()
    if webhook_secret:
        signature = request.headers.get("Crypto-Pay-API-Signature")
        if not verify_webhook_signature(token=webhook_secret, body=body, signature=signature):
            logger.warning("CryptoPay webhook signature mismatch")
            return web.Response(text="ok")

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("CryptoPay webhook: invalid JSON")
        return web.Response(text="ok")

    payload = data.get("payload") or data.get("invoice") or data.get("object") or {}
    invoice_id = payload.get("invoice_id") or payload.get("id")
    invoice_payload = payload.get("payload")

    if invoice_id:
        asyncio.create_task(_handle_cryptopay(int(invoice_id), invoice_payload))

    return web.Response(text="ok")


async def yookassa_webhook(request: web.Request) -> web.Response:
    secret = request.match_info.get("secret")
    webhook_path_secret = getattr(settings, "yookassa_webhook_path_secret", None)
    if webhook_path_secret and secret != webhook_path_secret:
        return web.Response(status=404)

    try:
        data = await request.json()
    except Exception:
        logger.warning("YooKassa webhook: invalid JSON")
        return web.Response(text="ok")
    
    event = data.get("event")
    if event and event != "payment.succeeded":
        return web.Response(text="ok")

    payment = data.get("object") or {}
    payment_id = payment.get("id")
    metadata = payment.get("metadata") or {}

    if payment_id:
        asyncio.create_task(_handle_yookassa(str(payment_id), metadata))

    return web.Response(text="ok")

def _platform_instructions_html(code: str) -> str:
    base = (
        "<ol>"
        "<li>Откройте приложение для подключения.</li>"
        "<li>Импортируйте ссылку или вставьте конфиг вручную.</li>"
        "<li>Выберите профиль и нажмите «Подключить».</li>"
        "</ol>"
    )
    if code == "ios":
        return (
            "<h3>Инструкция для iOS</h3>"
            "<p>Установите Happ или совместимый клиент и импортируйте ссылку.</p>"
            + base
        )
    if code == "android":
        return (
            "<h3>Инструкция для Android</h3>"
            "<p>Установите Happ или другой VLESS-клиент и импортируйте ссылку.</p>"
            + base
        )
    if code == "windows":
        return (
            "<h3>Инструкция для Windows</h3>"
            "<p>Установите клиент и импортируйте ссылку или конфиг.</p>"
            + base
        )
    if code == "macos":
        return (
            "<h3>Инструкция для macOS</h3>"
            "<p>Установите клиент и импортируйте ссылку или конфиг.</p>"
            + base
        )
    if code == "linux":
        return (
            "<h3>Инструкция для Linux</h3>"
            "<p>Установите клиент и добавьте конфиг.</p>"
            + base
        )
    return "<h3>Инструкция</h3>" + base


async def connect_page(request: web.Request) -> web.Response:
    token = request.match_info.get("token")
    platform = request.match_info.get("platform")
    parsed = verify_connect_token(token or "")
    if not parsed:
        return web.Response(status=404, text="Invalid token")
    async with session_scope() as session:
        device = await session.get(Device, parsed.device_id)
        if not device or device.user_id != parsed.user_id:
            return web.Response(status=404, text="Device not found")
    marz = _marzban_client()
    try:
        link = None
        subscription_url = None
        if device.marzban_username:
            user_data = await marz.get_user(device.marzban_username)
            if isinstance(user_data, dict):
                links = user_data.get("links") or []
                link = links[0] if links else None
                subscription_url = make_absolute_url(user_data.get("subscription_url"))
    finally:
        await marz.close()

    plain_url = subscription_url
    crypt_url = None
    if plain_url:
        _, crypt_url = await build_happ_links(plain_url)

    vless_block = f"<pre><code>{html.escape(link or '')}</code></pre>" if link else "<p>—</p>"
    happ_block = (
        f'<a class="btn" href="{html.escape(crypt_url)}">Добавить в Happ</a>'
        if crypt_url
        else ""
    )
    sub_block = (
        f'<a class="btn" href="{html.escape(plain_url)}">Открыть подписку</a>'
        if plain_url
        else ""
    )
    instructions = _platform_instructions_html(platform or "")
    html_body = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>Qdenzo Connect</title>
        <style>
          body {{ font-family: Arial, sans-serif; padding: 24px; max-width: 720px; margin: 0 auto; }}
          .btn {{ display: inline-block; margin: 6px 6px 6px 0; padding: 10px 14px; background: #1f6feb; color: #fff; text-decoration: none; border-radius: 6px; }}
          .section {{ margin-top: 18px; }}
          code {{ word-break: break-all; white-space: pre-wrap; }}
        </style>
      </head>
      <body>
        <h2>Подключение устройства</h2>
        <p>Выберите платформу:</p>
        <div>
          <a class="btn" href="./android">Android</a>
          <a class="btn" href="./ios">iOS</a>
          <a class="btn" href="./windows">Windows</a>
          <a class="btn" href="./macos">macOS</a>
          <a class="btn" href="./linux">Linux</a>
        </div>
        <div class="section">{instructions}</div>
        <div class="section">
          <h3>Ссылка подписки</h3>
          {sub_block or "<p>Подписка пока недоступна.</p>"}
        </div>
        <div class="section">
          <h3>VLESS конфиг</h3>
          {vless_block}
        </div>
        <div class="section">
          <h3>Happ</h3>
          {happ_block or "<p>Импорт в Happ временно недоступен.</p>"}
        </div>
      </body>
    </html>
    """
    return web.Response(text=html_body, content_type="text/html")



async def start_webhook_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_post("/webhook/cryptopay/{secret}", cryptopay_webhook)
    app.router.add_post("/webhook/yookassa/{secret}", yookassa_webhook)
    app.router.add_get("/connect/{token}", connect_page)
    app.router.add_get("/connect/{token}/{platform}", connect_page)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webhook_host, settings.webhook_port)
    await site.start()
    logger.info("Webhook server started on %s:%s", settings.webhook_host, settings.webhook_port)
    return runner


async def stop_webhook_server(runner: web.AppRunner | None) -> None:
    if not runner:
        return
    await runner.cleanup()