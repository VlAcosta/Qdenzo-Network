# -*- coding: utf-8 -*-

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import session_scope
from ..keyboards.common import back_kb
from ..keyboards.devices import device_menu_kb, device_type_kb, devices_list_kb
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
from ..utils.text import h

router = Router()


class DeviceStates(StatesGroup):
    choosing_new_device_name = State()
    renaming_device = State()

def _type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)

async def _show_devices(call_or_message, *, user_id: int) -> None:
    async with session_scope() as session:
        sub = await get_or_create_subscription(session, user_id)
        devices = await list_devices(session, user_id)

    can_add = len([d for d in devices if d.status != 'deleted']) < sub.devices_limit
    text = (
        "📱 <b>Ваши устройства</b>\n\n"
        f"Лимит по тарифу: <b>{sub.devices_limit}</b>\n"
        "Выберите устройство или добавьте новое."
    )
    kb = devices_list_kb(devices, can_add=can_add)
    if isinstance(call_or_message, CallbackQuery):
        await call_or_message.message.edit_text(text, reply_markup=kb)
        await call_or_message.answer()
    else:
        await call_or_message.answer(text, reply_markup=kb)


@router.message(Command('devices'))
async def cmd_devices(message: Message) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(session=session, tg_id=message.from_user.id, username=message.from_user.username, first_name=message.from_user.first_name, ref_code=None)
    await _show_devices(message, user_id=user.id)


@router.callback_query(F.data == 'devices')
async def cb_devices(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(session=session, tg_id=call.from_user.id, username=call.from_user.username, first_name=call.from_user.first_name, ref_code=None)
    await _show_devices(call, user_id=user.id)


@router.callback_query(F.data.startswith('dev:view:'))
async def cb_device_view(call: CallbackQuery) -> None:
    device_id = int(call.data.split(':')[-1])
    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
            await call.answer('Устройство не найдено', show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)

    status = '✅ активно' if device.status == 'active' else ('⛔️ отключено' if device.status == 'disabled' else '🗑 удалено')
    text = (
        "📲 <b>Устройство</b>\n\n"
        f"Название: <b>{h(device.label)}</b>\n"
        f"Тип: <b>{h(DEVICE_TYPES.get(device.device_type, device.device_type))}</b>\n"
        f"Статус: <b>{status}</b>\n\n"
        "Действия ниже:"
    )
    await call.message.edit_text(
        text,
        reply_markup=device_menu_kb(device.id, is_active=device.status == 'active'),
    )
    await call.answer()


@router.callback_query(F.data == 'dev:add')
async def cb_add_device(call: CallbackQuery, state: FSMContext) -> None:
    async with session_scope() as session:
        user = await get_or_create_user(session=session, tg_id=call.from_user.id, username=call.from_user.username, first_name=call.from_user.first_name, ref_code=None)
        sub = await get_or_create_subscription(session, user.id)
        devices = await list_devices(session, user.id)

    if len([d for d in devices if d.status != 'deleted']) >= sub.devices_limit:
        await call.answer('Лимит устройств исчерпан', show_alert=True)
        return

    await state.clear()
    await call.message.edit_text(
        "➕ <b>Добавить устройство</b>\n\nВыберите тип устройства:",
        reply_markup=device_type_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith('dev:type:'))
async def cb_choose_type(call: CallbackQuery, state: FSMContext) -> None:
    device_type = call.data.split(':')[-1]
    if device_type not in DEVICE_TYPES:
        await call.answer('Неизвестный тип', show_alert=True)
        return
    await state.set_state(DeviceStates.choosing_new_device_name)
    await state.update_data(device_type=device_type)
    await call.message.edit_text(
        "✍️ Отправьте <b>название</b> для устройства (например: <i>Мой iPhone</i>).\n"
        "\nМожно просто написать: Телефон / ПК / ТВ.",
        reply_markup=back_kb('devices'),
    )
    await call.answer()


@router.message(DeviceStates.choosing_new_device_name)
async def msg_new_device_name(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    device_type = data.get('device_type')
    label = (message.text or '').strip()
    if not label:
        await message.answer('Отправьте текст с названием устройства.')
        return

    async with session_scope() as session:
        user = await get_or_create_user(session=session, tg_id=message.from_user.id, username=message.from_user.username, first_name=message.from_user.first_name, ref_code=None)
        sub = await get_or_create_subscription(session, user.id)
        if not is_active(sub):
            await message.answer(
                "⛔️ У вас нет активной подписки.\n\nСначала оформите тариф в разделе <b>Купить</b>.",
                reply_markup=back_kb('buy'),
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
    await message.answer(
        f"✅ Устройство <b>{h(device.label)}</b> добавлено.\n\nТеперь получите конфиг в меню устройства.",
        reply_markup=back_kb('devices'),
    )


@router.callback_query(F.data.startswith('dev:rename:'))
async def cb_rename_device(call: CallbackQuery, state: FSMContext) -> None:
    device_id = int(call.data.split(':')[-1])
    await state.set_state(DeviceStates.renaming_device)
    await state.update_data(device_id=device_id)
    await call.message.edit_text(
        "✏️ Отправьте новое название устройства:",
        reply_markup=back_kb('devices'),
    )
    await call.answer()


@router.message(DeviceStates.renaming_device)
async def msg_rename_device(message: Message, state: FSMContext) -> None:
    new_name = (message.text or '').strip()
    if not new_name:
        await message.answer('Отправьте текст с названием.')
        return
    data = await state.get_data()
    device_id = int(data.get('device_id'))

    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != message.from_user.id:
            await message.answer('Устройство не найдено.')
            await state.clear()
            return
        await rename_device(session, device, new_name)

    await state.clear()
    await message.answer('✅ Название обновлено.', reply_markup=back_kb('devices'))


@router.callback_query(F.data.startswith('dev:cfg:'))
async def cb_device_cfg(call: CallbackQuery) -> None:
    device_id = int(call.data.split(':')[-1])

    async with session_scope() as session:
        device = await get_device(session, device_id)
        if not device or device.user.tg_id != call.from_user.id:
            await call.answer('Устройство не найдено', show_alert=True)
            return
        sub = await get_or_create_subscription(session, device.user_id)

    if not is_active(sub):
        await call.answer('Подписка не активна', show_alert=True)
        return

    marz = MarzbanClient(
        base_url=str(settings.marzban_base_url),
        username=settings.marzban_username,
        password=settings.marzban_password,
        verify_ssl=settings.marzban_verify_ssl,
    )
    try:
        if device.marzban_username:
            link, subscription_url = await get_device_connection_links(marz, device.marzban_username)
        else:
            link, subscription_url = None, None
    finally:
        await marz.close()

    # Show both (link + subscription) if available
    btn_rows = []
    if link:
        btn_rows.append([
            {'text': '🔗 Открыть / Импортировать', 'url': link}
        ])
    if subscription_url:
        btn_rows.append([
            {'text': '📥 Подписка (subscription)', 'url': subscription_url}
        ])
    btn_rows.append([
        {'text': '⬅️ Назад', 'callback_data': f'dev:view:{device_id}'}
    ])

    # Build InlineKeyboardMarkup manually (avoid extra imports)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(**btn_rows[0][0])] if btn_rows and 'url' in btn_rows[0][0] else [],
    ])
    # Above is messy; we'll build properly below
    rows = []
    for row in btn_rows:
        row_btns = []
        for b in row:
            if 'url' in b:
                row_btns.append(InlineKeyboardButton(text=b['text'], url=b['url']))
            else:
                row_btns.append(InlineKeyboardButton(text=b['text'], callback_data=b['callback_data']))
        rows.append(row_btns)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    link_text = link or subscription_url or '—'
    text = (
        "🔗 <b>Конфиг для устройства</b>\n\n"
        "Нажмите кнопку ниже или скопируйте ссылку:\n\n"
        f"<pre><code>{h(link_text)}</code></pre>"
    )
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# Placeholders for toggle/delete (implemented later)


@router.callback_query(F.data.startswith('dev:toggle:'))
async def cb_dev_toggle(call: CallbackQuery, bot: Bot) -> None:
    device_id = int(call.data.split(':', 2)[2])
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        device = await get_device(session, device_id)
        if not device or device.user_id != user.id:
            await call.answer('Устройство не найдено', show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)

        marz = MarzbanClient(
            base_url=str(settings.marzban_base_url),
            username=settings.marzban_username,
            password=settings.marzban_password,
            verify_ssl=settings.marzban_verify_ssl,
        )
        try:
            if device.status == 'active':
                # Disable
                try:
                    await marz.update_user(username=device.marzban_username, status='disabled')
                except Exception:
                    pass
                device.status = 'disabled'
                session.add(device)
                await session.commit()
                await call.answer('Отключено')
            else:
                if not is_active(sub):
                    await call.answer('Подписка не активна', show_alert=True)
                    return
                active_cnt = await count_active_devices(session, user.id)
                if active_cnt >= sub.devices_limit:
                    await call.answer('Достигнут лимит устройств. Купите план выше.', show_alert=True)
                    return
                exp_ts = int(sub.expires_at.timestamp()) if sub.expires_at else 0
                try:
                    await marz.update_user(username=device.marzban_username, status='active', expire=exp_ts)
                except Exception:
                    pass
                device.status = 'active'
                session.add(device)
                await session.commit()
                await call.answer('Включено')
        finally:
            await marz.close()

    # Refresh device view
    await _show_device_view(call, device_id)


@router.callback_query(F.data.startswith('dev:delete:'))
async def cb_dev_delete(call: CallbackQuery, bot: Bot) -> None:
    device_id = int(call.data.split(':', 2)[2])
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        device = await get_device(session, device_id)
        if not device or device.user_id != user.id:
            await call.answer('Устройство не найдено', show_alert=True)
            return

        marz = MarzbanClient(
            base_url=str(settings.marzban_base_url),
            username=settings.marzban_username,
            password=settings.marzban_password,
            verify_ssl=settings.marzban_verify_ssl,
        )
        try:
            # Safer than delete: just disable
            try:
                await marz.update_user(username=device.marzban_username, status='disabled')
            except Exception:
                pass
        finally:
            await marz.close()

        device.status = 'deleted'
        session.add(device)
        await session.commit()

    await call.answer('Удалено')
    # Back to list
    await cb_devices(call)


async def _show_device_view(call: CallbackQuery, device_id: int) -> None:
    """Render device screen without relying on call.data format."""
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer('Сначала /start', show_alert=True)
            return
        device = await get_device(session, device_id)
        if not device or device.user_id != user.id:
            await call.answer('Устройство не найдено', show_alert=True)
            return

    status = '✅ Активно' if device.status == 'active' else ('⛔️ Выключено' if device.status == 'disabled' else '🗑 Удалено')
    text = (
        f"<b>Устройство #{device.slot}</b>\n"
        f"Тип: {_type_title(device.device_type)}\n"
        f"Имя: <b>{h(device.label)}</b>\n"
        f"Статус: {status}"
    )
    await call.message.edit_text(
        text,
        reply_markup=device_menu_kb(device_id, is_active=device.status == 'active'),
    )
    await call.answer()
