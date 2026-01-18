# -*- coding: utf-8 -*-

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..config import settings
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from ..db import session_scope
from ..keyboards.devices import (
    device_delete_confirm_kb,
    device_menu_kb,
    device_quick_type_kb,
    device_type_kb,
    devices_list_kb,
)
from ..keyboards.nav import nav_kb
from loguru import logger

from ..marzban.client import MarzbanClient, MarzbanError
from ..models import Device
from ..services.devices import (
    DEVICE_TYPES,
    count_active_devices,
    create_device,
    display_label,
    get_device,
    get_device_connection_links,
    list_devices,
    rename_device,
)
from ..services.subscriptions import get_or_create_subscription, is_active
from ..services.users import ensure_user
from ..services.happ_proxy import HappProxyConfig, _with_install_id, add_install_code
from ..services.happ_connect import build_happ_links
from ..utils.connect_messages import build_auto_connect_message
from ..utils.text import h
from ..utils.urls import build_public_url, is_http_url, mask_url, sanitize_inline_url
from ..utils.connect import create_connect_token
from ..utils.telegram import edit_message_text, safe_answer_callback, send_html_with_photo

router = Router()

HAPP_URL_DEFAULT = "https://www.happ.su/"


class DeviceStates(StatesGroup):
    renaming_device = State()

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

def _connect_instruction_text() -> str:
    return (
        "📄 <b>Инструкция по подключению</b>\n\n"
        "1) Установите приложение Happ.\n"
        "2) Нажмите «Add to Happ» или откройте обычную ссылку.\n"
        "3) Подтвердите импорт и дождитесь активации.\n\n"
        "Если импорт не сработал — используйте обычную ссылку и выберите профиль вручную."
    )

def _platform_title(code: str) -> str:
    return {
        "android": "Android",
        "ios": "iOS",
        "windows": "Windows",
        "macos": "macOS",
        "linux": "Linux",
    }.get(code, "Устройство")


def _platform_instructions(code: str) -> str:
    base = (
        "1) Откройте приложение для подключения.\n"
        "2) Импортируйте ссылку или вставьте конфиг вручную.\n"
        "3) Выберите профиль и нажмите «Подключить».\n"
    )
    if code == "ios":
        return (
            "📄 <b>Инструкция для iOS</b>\n\n"
            "1) Установите Happ или совместимый клиент.\n"
            "2) Нажмите «Импортировать» и вставьте ссылку.\n"
            "3) Подтвердите добавление профиля.\n\n"
            + base
        )
    if code == "android":
        return (
            "📄 <b>Инструкция для Android</b>\n\n"
            "1) Установите Happ или другой VLESS-клиент.\n"
            "2) Импортируйте ссылку или вставьте конфиг.\n"
            "3) Сохраните профиль.\n\n"
            + base
        )
    if code == "windows":
        return (
            "📄 <b>Инструкция для Windows</b>\n\n"
            "1) Установите клиент (Happ или другой VLESS).\n"
            "2) Импортируйте ссылку или добавьте конфиг.\n"
            "3) Включите соединение.\n\n"
            + base
        )
    if code == "macos":
        return (
            "📄 <b>Инструкция для macOS</b>\n\n"
            "1) Установите клиент (Happ или другой VLESS).\n"
            "2) Импортируйте ссылку или вставьте конфиг.\n"
            "3) Запустите подключение.\n\n"
            + base
        )
    if code == "linux":
        return (
            "📄 <b>Инструкция для Linux</b>\n\n"
            "1) Установите клиент VLESS.\n"
            "2) Импортируйте ссылку или добавьте конфиг.\n"
            "3) Подключитесь к сети.\n\n"
            + base
        )
    return "📄 <b>Инструкция</b>\n\n" + base


def _connect_page_path(device: Device) -> str:
    token = create_connect_token(device_id=device.id, user_id=device.user_id)
    return f"/connect/{token}"


def _connect_page_url(device: Device) -> str | None:
    return build_public_url(_connect_page_path(device))


def _connect_actions_kb(
    *,
    device: Device,
    has_plain_link: bool,
    platform: str | None,
    has_happ: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    connect_url = sanitize_inline_url(_connect_page_url(device))
    if connect_url:
        rows.append([InlineKeyboardButton(text="🚀 Подключить (рекомендовано)", url=connect_url)])
    else:
        rows.append([InlineKeyboardButton(text="🚀 Подключить (рекомендовано)", callback_data=f"dev:connect_link:{device.id}")])
    if has_happ:
        rows.append([InlineKeyboardButton(text="🚀 Импорт в Happ", callback_data=f"dev:happ_import:{device.id}")])
    rows.append([InlineKeyboardButton(text="🔗 Обычная ссылка", callback_data=f"dev:show_link:{device.id}")])
    if platform:
        rows.append([InlineKeyboardButton(text=f"📄 Инструкция ({_platform_title(platform)})", callback_data=f"dev:instruction:{device.id}:{platform}")])
    else:
        rows.append([InlineKeyboardButton(text="📄 Инструкция", callback_data=f"dev:instruction:{device.id}:choose")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device.id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _happ_proxy_cfg() -> HappProxyConfig | None:
    if not (settings.happ_proxy_api_base and settings.happ_proxy_provider_code and settings.happ_proxy_auth_key):
        return None
    return HappProxyConfig(
        api_base=settings.happ_proxy_api_base,
        provider_code=settings.happ_proxy_provider_code,
        auth_key=settings.happ_proxy_auth_key,
    )


async def _resolve_device_urls(device) -> tuple[str | None, str | None]:
    if not device.marzban_username:
        return None, None
    marz = _marzban_client()
    try:
        link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    finally:
        await marz.close()
    return link, subscription_url


async def _ensure_install_code(session, device, *, install_limit: int) -> str | None:
    cfg = _happ_proxy_cfg()
    if not cfg:
        return None
    if device.happ_install_code:
        return device.happ_install_code
    install_code = await add_install_code(
        cfg,
        install_limit=install_limit,
        note=f"user={device.user_id} dev={device.id}",
    )
    device.happ_install_code = install_code
    session.add(device)
    await session.commit()
    return install_code


async def _build_connect_links(
    session,
    device,
    *,
    install_limit: int,
) -> tuple[str | None, str | None, str | None]:
    link, subscription_url = await _resolve_device_urls(device)
    base_url = subscription_url if is_http_url(subscription_url) else None
    if not base_url:
        return None, None, link
    try:
        install_code = await _ensure_install_code(session, device, install_limit=install_limit)
    except Exception:
        install_code = None
    limited_url = _with_install_id(base_url, install_code) if install_code else base_url
    try:
        _, crypt_url = await build_happ_links(limited_url)
    except Exception:
        crypt_url = None
    logger.debug(
        "Connect links resolved device_id={} plain_url={} crypt_url={}",
        device.id,
        mask_url(limited_url),
        mask_url(crypt_url),
    )
    return limited_url, crypt_url, link


async def _build_happ_connect_links(
    session,
    device,
    *,
    install_limit: int,
    marz: MarzbanClient,
) -> tuple[str | None, str | None, str | None]:
    link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    base_url = subscription_url if is_http_url(subscription_url) else None
    if not base_url:
        return None, None, link
    try:
        install_code = await _ensure_install_code(session, device, install_limit=install_limit)
    except Exception:
        install_code = None
    limited_url = _with_install_id(base_url, install_code) if install_code else base_url
    try:
        plain_url, crypt_url = await build_happ_links(limited_url)
        logger.debug(
            "Happ connect links resolved device_id={} plain_url={} crypt_url={}",
            device.id,
            mask_url(plain_url),
            mask_url(crypt_url),
        )
        return plain_url, crypt_url, link
    except Exception:
        return limited_url, None, link




async def _show_connect_screen(call_or_message, *, device_id: int) -> None:
    if isinstance(call_or_message, CallbackQuery):
        await safe_answer_callback(call_or_message)
    async with session_scope() as session:
        result = await session.execute(
            select(Device).options(selectinload(Device.user)).where(Device.id == device_id)
        )
        device = result.scalar_one_or_none()
        if not device:
            if isinstance(call_or_message, CallbackQuery):
                await safe_answer_callback(call_or_message, "Устройство не найдено", show_alert=True)
            else:
                await send_html_with_photo(
                    call_or_message,
                    "Устройство не найдено",
                    photo_path=settings.start_photo_path,
                )
            return
        if hasattr(call_or_message, "from_user") and device.user.tg_id != call_or_message.from_user.id:
            if isinstance(call_or_message, CallbackQuery):
                await safe_answer_callback(call_or_message, "Устройство не найдено", show_alert=True)
            else:
                await send_html_with_photo(
                    call_or_message,
                    "Устройство не найдено",
                    photo_path=settings.start_photo_path,
                )
            return
        sub = await get_or_create_subscription(session, device.user_id)
        limited_url, crypt_url, vless_link = await _build_connect_links(
            session,
            device,
            install_limit=sub.devices_limit,
        )

    if not limited_url and not vless_link:
        text = "Сервис временно отвечает медленно, попробуйте ещё раз."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"dev:connect:{device_id}")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
            ],
        ])
        if isinstance(call_or_message, CallbackQuery):
            await edit_message_text(call_or_message, text, reply_markup=kb)
            await safe_answer_callback(call_or_message)
        else:
            await send_html_with_photo(
                call_or_message,
                text,
                reply_markup=kb,
                photo_path=settings.start_photo_path,
            )
        return

    text = (
        "🚀 <b>Подключение устройства</b>\n\n"
        "Рекомендуем использовать быстрый мастер — он подберёт шаги под ваше устройство.\n"
        "Выберите способ ниже 👇"
    )
    text += f"\n\n<b>Ссылка мастера:</b> <code>{h(_connect_page_path(device))}</code>"
    if vless_link:
        text += f"\n\n<pre><code>{h(vless_link)}</code></pre>"
    if crypt_url is None:
        text += "\n\n⚠️ Шифрованный импорт временно недоступен — используйте обычную ссылку."
    platform = device.user.last_device_platform
    kb = _connect_actions_kb(
        device=device,
        has_plain_link=bool(limited_url),
        platform=platform,
        has_happ=bool(crypt_url),
    )
    if isinstance(call_or_message, CallbackQuery):
        await edit_message_text(call_or_message, text, reply_markup=kb)
        await safe_answer_callback(call_or_message,)
    else:
        await send_html_with_photo(
            call_or_message,
            text,
            reply_markup=kb,
            photo_path=settings.start_photo_path,
        )

def _type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)


async def _show_devices(call_or_message, *, user_id: int) -> None:
    if isinstance(call_or_message, CallbackQuery):
        await safe_answer_callback(call_or_message)
    async with session_scope() as session:
        sub = await get_or_create_subscription(session, user_id)
        devices = await list_devices(session, user_id)

    active_devices = [d for d in devices if d.status != "deleted"]
    can_add = len(active_devices) < sub.devices_limit
    lines = [
        f"• <b>{h(display_label(d))}</b> — {h(_type_title(d.device_type))}"
        for d in active_devices
    ]
    text = (
        "📱 <b>Ваши устройства</b>\n\n"
        f"Лимит по тарифу: <b>{sub.devices_limit}</b>\n\n"
        "<b>Список устройств:</b>\n"
        + ("\n".join(lines) if lines else "—")
        + "\n\n"
        "Выберите устройство или добавьте новое."
    )
    kb = devices_list_kb(devices, can_add=can_add)

    if isinstance(call_or_message, CallbackQuery):
        await edit_message_text(call_or_message, text, reply_markup=kb)
        await safe_answer_callback(call_or_message,)
    else:
        await send_html_with_photo(
            call_or_message,
            text,
            reply_markup=kb,
            photo_path=settings.start_photo_path,
        )


@router.message(Command("devices"))
async def cmd_devices(message: Message) -> None:
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user)
    await _show_devices(message, user_id=user.id)


@router.callback_query(F.data == "devices")
async def cb_devices(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
    await _show_devices(call, user_id=user.id)


@router.callback_query(F.data.startswith("dev:view:"))
async def cb_device_view(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await safe_answer_callback(call, "Устройство не найдено", show_alert=True)
            return

    status = "✅ активно" if device.status == "active" else ("❄️ заморожено" if device.status == "disabled" else "🗑 удалено")
    text = (
        "📲 <b>Устройство</b>\n\n"
        f"Название: <b>{h(display_label(device))}</b>\n"
        f"Тип: <b>{h(_type_title(device.device_type))}</b>\n"
        f"Статус: <b>{status}</b>\n\n"
        "Действия ниже:"
    )
    await edit_message_text(call, text, reply_markup=device_menu_kb(device.id, is_active=device.status == "active"))
    await safe_answer_callback(call)


@router.callback_query(F.data == "dev:add")
async def cb_add_device(call: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)
        devices = await list_devices(session, user.id)

    if not is_active(sub):
        await edit_message_text(
            call,
            "⛔️ Для подключения устройства нужна активная подписка.\n\n"
            "Перейдите в раздел <b>Купить</b> / <b>Управление</b>.",
            reply_markup=nav_kb(back_cb="buy", home_cb="back"),
        )
        await call.answer()
        return

    if len([d for d in devices if d.status != "deleted"]) >= sub.devices_limit:
        await call.answer(
            "Лимит устройств исчерпан. Удалите или заморозьте старое устройство, чтобы добавить новое.",
            show_alert=True,
        )
        await cb_devices(call)
        return

    hint = ""
    if user.last_device_type in DEVICE_TYPES:
        hint = f"\nПо умолчанию: {_type_title(user.last_device_type)}."

    await state.clear()
    await edit_message_text(
        call,
        "➕ <b>Добавить устройство</b>\n\n"
        "Мы предложим имя автоматически — его можно изменить позже.\n"
        "Выберите тип устройства:"
        f"{hint}",
        reply_markup=device_quick_type_kb(user.last_device_type),
    )
    await call.answer()


@router.callback_query(F.data == "dev:type:more")
async def cb_device_type_more(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    await edit_message_text(
        call,
        "Выберите тип устройства:",
        reply_markup=device_type_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("dev:type:"))
async def cb_choose_type(call: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(call)
    device_type = call.data.split(":")[-1]
    if device_type not in DEVICE_TYPES:
        await call.answer("Неизвестный тип", show_alert=True)
        return

    await state.clear()
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)

        if not is_active(sub):
            await edit_message_text(
                call,
                "⛔️ У вас нет активной подписки.\n\nСначала оформите тариф в разделе <b>Купить</b>.",
                reply_markup=nav_kb(back_cb="buy", home_cb="back"),
            )
            await call.answer()
            return

        marz = _marzban_client()
        try:
            try:
                label = user.last_device_label if user.last_device_type == device_type else None
                device = await create_device(
                    session=session,
                    marz=marz,
                    user=user,
                    sub=sub,
                    device_type=device_type,
                    label=label,
                )
            except MarzbanError as exc:
                logger.exception(
                    "Marzban provisioning failed for tg_id=%s device_type=%s: %s",
                    user.tg_id,
                    device_type,
                    exc,
                )
                await edit_message_text(
                    call,
                    "⚠️ Панель временно недоступна или неверные данные Marzban.\n"
                    "Обратитесь в поддержку.",
                    reply_markup=nav_kb(back_cb="devices", home_cb="back"),
                )
                await call.answer()
                return
            plain_url, crypt_url, vless_link = await _build_happ_connect_links(
                session,
                device,
                install_limit=sub.devices_limit,
                marz=marz,

            )
        finally:
            await marz.close()

    await edit_message_text(
        call,
        f"✅ Устройство <b>{h(device.label)}</b> добавлено!\n\n"
        "Теперь подключите его 👇",
    )
    if not plain_url and not vless_link:
        await call.message.answer(
            "Сервис временно отвечает медленно, попробуйте ещё раз."
        )
        await call.answer()
        return

    message_text = build_auto_connect_message(vless_link)
    await call.message.answer(
        message_text,
        reply_markup=_connect_actions_kb(
            device=device,
            has_plain_link=bool(plain_url),
            platform=user.last_device_platform,
            has_happ=bool(crypt_url),
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("dev:rename:"))
async def cb_rename_device(call: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    await state.set_state(DeviceStates.renaming_device)
    await state.update_data(device_id=device_id)

    await edit_message_text(
        call,
        "✏️ Отправьте новое название устройства:",
        reply_markup=nav_kb(back_cb=f"dev:view:{device_id}", home_cb="back"),
    )
    await call.answer()


@router.message(DeviceStates.renaming_device)
async def msg_rename_device(message: Message, state: FSMContext) -> None:
    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("Отправьте текст с названием.")
        return

    data = await state.get_data()
    device_id = int(data.get("device_id"))

    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await message.answer("Устройство не найдено.")
            await state.clear()
            return
        await rename_device(session, device, new_name)

    await state.clear()
    await message.answer("✅ Название обновлено.", reply_markup=nav_kb(back_cb="devices", home_cb="back"))


@router.callback_query(F.data.startswith("dev:cfg:"))
async def cb_device_cfg(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await call.answer("Устройство не найдено", show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)

    if not is_active(sub):
        await call.answer("Подписка не активна", show_alert=True)
        return

    marz = _marzban_client()
    try:
        link, subscription_url = (None, None)
        if device.marzban_username:
            link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    finally:
        await marz.close()

    rows = []
    safe_link = sanitize_inline_url(link)
    safe_subscription = sanitize_inline_url(subscription_url)
    if safe_link:
        rows.append([InlineKeyboardButton(text="🔗 Открыть / Импортировать", url=safe_link)])
    if safe_subscription:
        rows.append([InlineKeyboardButton(text="📥 Подписка (subscription)", url=safe_subscription)])
    if link and not is_http_url(link):
        rows.append([InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data=f"dev:copy_link:{device_id}")])
    if not link and not subscription_url:
        rows.append([InlineKeyboardButton(text="🔄 Повторить", callback_data=f"dev:cfg:{device_id}")])
        rows.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ])
        text = "Сервис временно отвечает медленно, попробуйте ещё раз."
        await edit_message_text(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])

    shown = link or subscription_url or "—"
    text = (
        "🔗 <b>Конфиг для устройства</b>\n\n"
        "Нажмите кнопку ниже или скопируйте ссылку:\n\n"
        f"<pre><code>{h(shown)}</code></pre>"
    )
    await edit_message_text(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("dev:connect:"))
async def cb_device_connect(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    await _show_connect_screen(call, device_id=device_id)

@router.callback_query(F.data.startswith("dev:happ_import:"))
async def cb_device_happ_import(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await call.answer("Устройство не найдено", show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)
        _, crypt_url, vless_link = await _build_connect_links(
            session,
            device,
            install_limit=sub.devices_limit,
        )
    if not crypt_url:
        text = (
            "Импорт в Happ временно недоступен. "
            "Используйте обычную ссылку или VLESS-конфиг."
        )
    else:
        text = (
            "🚀 <b>Импорт в Happ</b>\n\n"
            "1) Откройте приложение Happ.\n"
            "2) Импортируйте ссылку ниже.\n\n"
            f"<pre><code>{h(crypt_url)}</code></pre>"
        )
    if vless_link:
        text += f"\n\n<pre><code>{h(vless_link)}</code></pre>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()



@router.callback_query(F.data.startswith("dev:connect_link:"))
async def cb_device_connect_link(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await call.answer("Устройство не найдено", show_alert=True)
            return
    connect_path = _connect_page_path(device)
    text = (
        "🔗 <b>Ссылка на мастер подключения</b>\n\n"
        "Скопируйте и откройте в браузере:\n\n"
        f"<pre><code>{h(connect_path)}</code></pre>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("dev:show_link:"))
async def cb_device_show_link(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await call.answer("Устройство не найдено", show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)
        limited_url, _, vless_link = await _build_connect_links(session, device, install_limit=sub.devices_limit)

    if not limited_url and not vless_link:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"dev:show_link:{device_id}")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
            ],
        ])
        await edit_message_text(call, "Сервис временно отвечает медленно, попробуйте ещё раз.", reply_markup=kb)
        return
    
    if vless_link and not limited_url:
        text = (
            "🔗 <b>Обычная ссылка</b>\n\n"
            "Скопируйте и импортируйте в клиент вручную:\n\n"
            f"<pre><code>{h(vless_link)}</code></pre>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data=f"dev:copy_link:{device_id}"),
        ], [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ]])
        await edit_message_text(call, text, reply_markup=kb)
        return


    text = (
        "🔗 <b>Обычная ссылка</b>\n\n"
        "Скопируйте и импортируйте в клиент вручную:\n\n"
        f"<pre><code>{h(limited_url)}</code></pre>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("dev:copy_link:"))
async def cb_device_copy_link(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        device = await get_device(session, device_id, user_id=user.id)
        if not device:
            await call.answer("Устройство не найдено", show_alert=True)
            return
    marz = _marzban_client()
    try:
        link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    finally:
        await marz.close()
    vless_link = link if link and not is_http_url(link) else None
    if not vless_link:
        await call.answer("Ссылка пока недоступна", show_alert=True)
        return
    text = (
        "📋 <b>Ссылка для подключения</b>\n\n"
        "Нажмите и удерживайте, чтобы скопировать:\n\n"
        f"<pre><code>{h(vless_link)}</code></pre>"
    )
    await call.message.answer(text)
    await call.answer()

def _platform_choice_kb(device_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Android", callback_data=f"dev:set_platform:{device_id}:android"),
            InlineKeyboardButton(text="iOS", callback_data=f"dev:set_platform:{device_id}:ios"),
        ],
        [
            InlineKeyboardButton(text="Windows", callback_data=f"dev:set_platform:{device_id}:windows"),
            InlineKeyboardButton(text="macOS", callback_data=f"dev:set_platform:{device_id}:macos"),
        ],
        [
            InlineKeyboardButton(text="Linux", callback_data=f"dev:set_platform:{device_id}:linux"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)



@router.callback_query(F.data.startswith("dev:instruction:"))
async def cb_device_instruction(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    parts = call.data.split(":")
    if len(parts) < 3:
        return
    _, _, device_id_s, *rest = parts
    device_id = int(device_id_s)
    platform = rest[0] if rest else None
    if platform == "choose" or not platform:
        await edit_message_text(
            call,
            "Выберите платформу, чтобы показать инструкцию:",
            reply_markup=_platform_choice_kb(device_id),
        )
        await call.answer()
        return
    text = _platform_instructions(platform)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("dev:set_platform:"))
async def cb_set_platform(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    parts = call.data.split(":")
    if len(parts) != 4:
        return
    _, _, device_id_s, platform = parts
    device_id = int(device_id_s)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        user.last_device_platform = platform
        session.add(user)
        await session.commit()
    text = _platform_instructions(platform)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data == "happ:help")
async def cb_happ_help(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    text = (
        "📄 <b>Как подключиться через Happ</b>\n\n"
        "1) Нажмите «Add to Happ».\n"
        "2) Подтвердите открытие приложения.\n"
        "3) Внутри Happ нажмите «Connect».\n\n"
        "Если импорт не сработал — используйте обычную ссылку."
    )
    await call.message.answer(text)
    await call.answer()