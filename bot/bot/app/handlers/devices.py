# -*- coding: utf-8 -*-

from aiogram import Bot, F, Router
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
    device_happ_kb,
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
from ..services.users import get_or_create_user, get_user_by_tg_id
from ..services.happ_proxy import HappProxyConfig, add_install_code
from ..services.happ_crypto import encrypt_subscription_url
from ..utils.text import h
from ..utils.telegram import edit_message_text

router = Router()

HAPP_URL_DEFAULT = "https://example.com/happ"


class DeviceStates(StatesGroup):
    waiting_happ_confirm = State()
    choosing_new_device_name = State()
    renaming_device = State()


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
    await state.set_state(DeviceStates.waiting_happ_confirm)

    happ_url = getattr(settings, "happ_url", None) or HAPP_URL_DEFAULT

    await edit_message_text(
        call,
        "🚀 <b>Подключение устройства</b>\n\n"
        "Сначала откройте приложение/скрипт (Happ).\n"
        "Затем нажмите <b>«Я открыл приложение»</b>.",
        reply_markup=device_happ_kb(
            happ_url=happ_url,
            continue_cb="dev:happ_ok",
            back_cb="devices",
        ),
    )
    await call.answer()


@router.callback_query(F.data == "dev:happ_ok")
async def cb_happ_ok(call: CallbackQuery, state: FSMContext) -> None:
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

    await state.set_state(DeviceStates.choosing_new_device_name)
    await state.update_data(device_type=device_type)

    await edit_message_text(
        call,
        "✍️ Отправьте <b>название</b> устройства (например: <i>Мой iPhone</i>).\n\n"
        "Можно просто написать: Телефон / ПК / ТВ.",
        reply_markup=nav_kb(back_cb="dev:add", home_cb="back"),
    )
    await call.answer()


@router.message(DeviceStates.choosing_new_device_name)
async def msg_new_device_name(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    device_type = data.get("device_type")
    label = (message.text or "").strip()

    if not label:
        await message.answer("Отправьте текст с названием устройства.")
        return

    async with session_scope() as session:
        user = await get_or_create_user(
            session=session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            ref_code=None,
            locale=message.from_user.language_code,
        )
        sub = await get_or_create_subscription(session, user.id)

        if not is_active(sub):
            await message.answer(
                "⛔️ У вас нет активной подписки.\n\nСначала оформите тариф в разделе <b>Купить</b>.",
                reply_markup=nav_kb(back_cb="buy", home_cb="back"),
            )
            await state.clear()
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
                label=label,
            )
        finally:
            await marz.close()

    await state.clear()

    # финальный экран
    cfg = HappProxyConfig(
        api_base=settings.happ_proxy_api_base,
        provider_code=settings.happ_proxy_provider_code,
        auth_key=settings.happ_proxy_auth_key,
    )

    # лимит по тарифу (можно сделать 1 на устройство или общий лимит)
    install_code = await add_install_code(
        cfg,
        install_limit=sub.devices_limit,
        note=f"user={device.user_id} dev={device.id}",
    )

    limited_url = _with_install_id(device.subscription_url, install_code)
    crypt_url = await encrypt_subscription_url(limited_url)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Импорт в Happ", url=crypt_url)],
        [InlineKeyboardButton(text="📲 Открыть Happ", url=str(settings.happ_url))],
        [InlineKeyboardButton(text="🔗 Показать ссылку", callback_data=f"dev:show_link:{device.id}")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev:view:{device.id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="back"),
        ],
    ])

    await message.answer(
        f"✅ Устройство <b>{h(device.label)}</b> добавлено!\n\n"
        "Теперь получите конфиг и подключитесь 👇",
        reply_markup=kb,
    )


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
