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
from ..marzban.client import MarzbanClient
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
from ..services.users import get_or_create_user
from ..services.happ_proxy import HappProxyConfig, _with_install_id, add_install_code
from ..services.happ_crypto import encrypt_subscription_url
from urllib.parse import quote
from ..utils.text import h
from ..utils.telegram import edit_message_text

router = Router()

HAPP_URL_DEFAULT = "https://www.happ.su/"


class DeviceStates(StatesGroup):
    renaming_device = State()

def _connect_instruction_text() -> str:
    return (
        "📄 <b>Инструкция по подключению</b>\n\n"
        "1) Установите приложение Happ.\n"
        "2) Нажмите «Импорт в Happ» (шифрованный импорт) или «Показать обычную ссылку».\n"
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

def _happ_add_link(subscription_url: str) -> str:
    happ_link = f"happ://add/{subscription_url}"
    if settings.happ_redirect_base:
        return f"{settings.happ_redirect_base}?app=happ&k={quote(happ_link, safe='')}"
    return happ_link


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
    base_url = _pick_connection_url(link, subscription_url)
    if not base_url:
        return None, None, None
    try:
        install_code = await _ensure_install_code(session, device, install_limit=install_limit)
    except Exception:
        install_code = None
    limited_url = _with_install_id(base_url, install_code) if install_code else base_url
    try:
        crypt_url = await encrypt_subscription_url(limited_url)
    except Exception:
        crypt_url = None
    happ_add_url = _happ_add_link(limited_url)
    return limited_url, crypt_url, happ_add_url


def _connect_kb(
    *,
    device_id: int,
    crypt_url: str | None,
    happ_add_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(text="⬇️ Установить Happ", url=settings.happ_url or HAPP_URL_DEFAULT)])
    if happ_add_url:
        rows.append([InlineKeyboardButton(text="🚀 Подключить в Happ", url=happ_add_url)])
    if crypt_url:
        rows.append([InlineKeyboardButton(text="🚀 Импорт в Happ (шифр.)", url=crypt_url)])
    rows.append([InlineKeyboardButton(text="🔗 Показать обычную ссылку", callback_data=f"dev:show_link:{device_id}")])
    rows.append([InlineKeyboardButton(text="📄 Инструкция", callback_data=f"dev:instruction:{device_id}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_connect_screen(call_or_message, *, device_id: int) -> None:
    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device:
            if isinstance(call_or_message, CallbackQuery):
                await call_or_message.answer("Устройство не найдено", show_alert=True)
            else:
                await call_or_message.answer("Устройство не найдено")
            return
        if hasattr(call_or_message, "from_user") and device.user.tg_id != call_or_message.from_user.id:
            if isinstance(call_or_message, CallbackQuery):
                await call_or_message.answer("Устройство не найдено", show_alert=True)
            else:
                await call_or_message.answer("Устройство не найдено")
            return
        sub = await get_or_create_subscription(session, device.user_id)
        limited_url, crypt_url, happ_add_url = await _build_connect_links(
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
            await call_or_message.answer()
        else:
            await call_or_message.answer(text, reply_markup=kb)
        return

    text = (
        "🚀 <b>Подключить устройство</b>\n\n"
        "Выберите способ подключения 👇"
    )
    if crypt_url is None:
        text += "\n\n⚠️ Шифрованный импорт временно недоступен — используйте обычную ссылку."
    kb = _connect_kb(device_id=device_id, crypt_url=crypt_url, happ_add_url=happ_add_url)
    if isinstance(call_or_message, CallbackQuery):
        await edit_message_text(call_or_message, text, reply_markup=kb)
        await call_or_message.answer()
    else:
        await call_or_message.answer(text, reply_markup=kb)

def _type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)


async def _show_devices(call_or_message, *, user_id: int) -> None:
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
        await call_or_message.answer()
    else:
        await call_or_message.answer(text, reply_markup=kb)


@router.message(Command("devices"))
async def cmd_devices(message: Message) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            ref_code=None,
            locale=message.from_user.language_code,
        )
    await _show_devices(message, user_id=user.id)


@router.callback_query(F.data == "devices")
async def cb_devices(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
    await _show_devices(call, user_id=user.id)


@router.callback_query(F.data.startswith("dev:view:"))
async def cb_device_view(call: CallbackQuery) -> None:
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
            await call.answer("Устройство не найдено", show_alert=True)
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
    await call.answer()


@router.callback_query(F.data == "dev:add")
async def cb_add_device(call: CallbackQuery, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
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
        await call.answer("Лимит устройств исчерпан", show_alert=True)
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
    device_type = call.data.split(":")[-1]
    if device_type not in DEVICE_TYPES:
        await call.answer("Неизвестный тип", show_alert=True)
        return

    await state.clear()
    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=call.from_user.id,
            username=call.from_user.username,
            first_name=call.from_user.first_name,
            ref_code=None,
            locale=call.from_user.language_code,
        )
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
    )
    try:
        device = await create_device(
            session=session,
            marz=marz,
            user=user,
            sub=sub,
            device_type=device_type,
            label=_type_title(device_type),
        )
    finally:
        await marz.close()

    await edit_message_text(
        call,
        f"✅ Устройство <b>{h(device.label)}</b> добавлено!\n\n"
        "Теперь подключите его 👇",
    )
    await _show_connect_screen(call, device_id=device.id)


@router.callback_query(F.data.startswith("dev:rename:"))
async def cb_rename_device(call: CallbackQuery, state: FSMContext) -> None:
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
    device_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
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
    device_id = int(call.data.split(":")[-1])
    await _show_connect_screen(call, device_id=device_id)


@router.callback_query(F.data.startswith("dev:show_link:"))
async def cb_device_show_link(call: CallbackQuery) -> None:
    device_id = int(call.data.split(":")[-1])
    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
            await call.answer("Устройство не найдено", show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)
        limited_url, _, _ = await _build_connect_links(session, device, install_limit=sub.devices_limit)

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
    device_id = int(call.data.split(":")[-1])
    text = _connect_instruction_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:connect:{device_id}"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
    ]])
    await edit_message_text(call, text, reply_markup=kb)
    await call.answer()