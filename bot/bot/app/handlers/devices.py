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
from ..db import session_scope
from ..keyboards.devices import (
    device_delete_confirm_kb,
    device_menu_kb,
    device_type_kb,
    devices_list_kb,
)
from ..keyboards.nav import nav_kb
from loguru import logger

from ..marzban.client import MarzbanClient, MarzbanError
from ..services.devices import (
    DEVICE_TYPES,
    count_active_devices,
    create_device,
    get_device,
    get_device_connection_links,
    list_devices,
    rename_device,
)
from ..services.subscriptions import get_or_create_subscription, is_active
from ..services.users import ensure_user
from ..services.happ_proxy import HappProxyConfig, _with_install_id, add_install_code
from ..services.happ_connect import build_happ_links
from ..utils.text import h
from ..utils.telegram import edit_message_text, safe_answer_callback, send_html_with_photo

router = Router()

HAPP_URL_DEFAULT = "https://www.happ.su/"


class DeviceStates(StatesGroup):
    renaming_device = State()

def _connect_instruction_text() -> str:
    return (
        "📄 <b>Инструкция по подключению</b>\n\n"
        "1) Установите приложение Happ.\n"
        "2) Нажмите «Add to Happ» или откройте обычную ссылку.\n"
        "3) Подтвердите импорт и дождитесь активации.\n\n"
        "Если импорт не сработал — используйте обычную ссылку и выберите профиль вручную."
    )


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
    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
    )
    try:
        link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    finally:
        await marz.close()
    return link, subscription_url


def _pick_connection_url(link: str | None, subscription_url: str | None) -> str | None:
    if settings.marzban_link_mode == "link":
        return link
    if settings.marzban_link_mode == "subscription":
        return subscription_url
    return subscription_url or link




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
) -> tuple[str | None, str | None]:
    link, subscription_url = await _resolve_device_urls(device)
    base_url = _pick_connection_url(link, subscription_url)
    if not base_url:
        return None, None
    try:
        install_code = await _ensure_install_code(session, device, install_limit=install_limit)
    except Exception:
        install_code = None
    limited_url = _with_install_id(base_url, install_code) if install_code else base_url
    try:
        _, crypt_url = await build_happ_links(limited_url)
    except Exception:
        crypt_url = None
    return limited_url, crypt_url


async def _build_happ_connect_links(session, device, *, install_limit: int, marz: MarzbanClient) -> tuple[str | None, str | None]:
    link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    base_url = _pick_connection_url(link, subscription_url)
    if not base_url:
        return None, None
    try:
        install_code = await _ensure_install_code(session, device, install_limit=install_limit)
    except Exception:
        install_code = None
    limited_url = _with_install_id(base_url, install_code) if install_code else base_url
    try:
        return await build_happ_links(limited_url)
    except Exception:
        return limited_url, None


def happ_connect_kb(*, plain_url: str, crypt_url: str | None) -> InlineKeyboardMarkup:
    """Standard one-tap Happ connect keyboard (Variant B)."""
    rows: list[list[InlineKeyboardButton]] = []
    if crypt_url:
        rows.append([InlineKeyboardButton(text="🚀 Добавить в Happ", url=crypt_url)])
    rows.append([InlineKeyboardButton(text="⬇️ Установить Happ", url=settings.happ_url or HAPP_URL_DEFAULT)])
    rows.append([InlineKeyboardButton(text="🔗 Обычная ссылка", url=plain_url)])
    rows.append([InlineKeyboardButton(text="📄 Инструкция", callback_data="happ:help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _connect_kb(
    *,
    device_id: int,
    plain_url: str,
    crypt_url: str | None,
) -> InlineKeyboardMarkup:
    kb = happ_connect_kb(plain_url=plain_url, crypt_url=crypt_url)
    rows = list(kb.inline_keyboard)
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_connect_screen(call_or_message, *, device_id: int) -> None:
    if isinstance(call_or_message, CallbackQuery):
        await safe_answer_callback(call_or_message)
    async with session_scope() as session:
        device = await get_device(session, device_id)
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
        limited_url, crypt_url = await _build_connect_links(
            session,
            device,
            install_limit=sub.devices_limit,
        )

    if not limited_url:
        text = "Ссылка для подключения пока недоступна. Попробуйте позже или обратитесь в поддержку."
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ]])
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
        "🚀 <b>Подключить устройство</b>\n\n"
        "Выберите способ подключения 👇"
    )
    if crypt_url is None:
        text += "\n\n⚠️ Шифрованный импорт временно недоступен — используйте обычную ссылку."
    kb = _connect_kb(device_id=device_id, plain_url=limited_url, crypt_url=crypt_url)
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

    can_add = len([d for d in devices if d.status != "deleted"]) < sub.devices_limit
    text = (
        "📱 <b>Ваши устройства</b>\n\n"
        f"Лимит по тарифу: <b>{sub.devices_limit}</b>\n"
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
        f"Название: <b>{h(device.label)}</b>\n"
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


    await state.clear()
    await edit_message_text(
        call,
        "➕ <b>Добавить устройство</b>\n\nВыберите тип устройства:",
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

    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
    )
    try:
        try:
            device = await create_device(
                session=session,
                marz=marz,
                user=user,
                sub=sub,
                device_type=device_type,
                label=_type_title(device_type),
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
        plain_url, crypt_url = await _build_happ_connect_links(
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
    if not plain_url:
        await call.message.answer(
            "Ссылка для подключения пока недоступна. Попробуйте позже или обратитесь в поддержку."
        )
        await call.answer()
        return

    # Variant B: auto-connect prompt after device creation.
    await call.message.answer(
        "Устройство успешно добавлено ✅\n\n"
        "Нажмите кнопку ниже — конфигурация будет\n"
        "импортирована в Happ автоматически.",
        reply_markup=happ_connect_kb(plain_url=plain_url, crypt_url=crypt_url),
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
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != message.from_user.id:
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

    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
        api_prefix=settings.marzban_api_prefix,
    )
    try:
        link, subscription_url = (None, None)
        if device.marzban_username:
            link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
    finally:
        await marz.close()

    rows = []
    if link:
        rows.append([InlineKeyboardButton(text="🔗 Открыть / Импортировать", url=link)])
    if subscription_url:
        rows.append([InlineKeyboardButton(text="📥 Подписка (subscription)", url=subscription_url)])
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


@router.callback_query(F.data.startswith("dev:show_link:"))
async def cb_device_show_link(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
            await call.answer("Устройство не найдено", show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)
        limited_url, _ = await _build_connect_links(session, device, install_limit=sub.devices_limit)

    if not limited_url:
        await call.answer("Ссылка пока недоступна", show_alert=True)
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


@router.callback_query(F.data.startswith("dev:instruction:"))
async def cb_device_instruction(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    device_id = int(call.data.split(":")[-1])
    text = _connect_instruction_text()
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