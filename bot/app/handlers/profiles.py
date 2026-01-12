# -*- coding: utf-8 -*-

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import session_scope
from ..keyboards.nav import nav_kb
from ..keyboards.profiles import (
    PROFILES,
    modes_root_kb,
    profiles_account_kb,
    profiles_device_list_kb,
    profiles_device_modes_kb,
)
from ..services.devices import get_device, list_devices, set_device_profile, type_title
from ..services.users import get_user_by_tg_id
from ..services.profiles import get_profile_code, set_profile_code
from ..services.subscriptions import get_or_create_subscription, is_active
from ..utils.telegram import edit_message_text
from ..utils.text import h

router = Router()


def _allowed_profiles(plan_code: str) -> set[str]:
    plan = (plan_code or "").lower()
    if plan == "family":
        return {"smart", "stream", "game", "low", "work", "kids"}
    if plan == "pro":
        return {"smart", "stream", "game", "low", "work"}
    # start / trial / unknown
    return {"smart", "low", "work"}


@router.callback_query(F.data.in_({"profiles", "modes"}))
@router.message(Command("profiles"))
async def show_profiles(event) -> None:
    if isinstance(event, Message):
        tg_id = event.from_user.id
        answer = event.answer
        is_cb = False
    else:
        tg_id = event.from_user.id
        answer = edit_message_text
        is_cb = True

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, tg_id)
        if not user:
            if is_cb:
                await event.answer("Сначала нажмите /start", show_alert=True)
            else:
                await event.answer("Сначала нажмите /start")
            return

        sub = await get_or_create_subscription(session, user.id)

    if not is_active(sub):
        text = (
            "⛔️ <b>Режимы доступны только при активной подписке.</b>\n\n"
            "Оформите тариф в разделе <b>Купить</b> / <b>Управление</b>."
        )
        await answer(event, text, reply_markup=nav_kb(back_cb="buy", home_cb="back"))
        if is_cb:
            await event.answer()
        return


    text = (
        "🧠 <b>Режимы — профили использования</b>\n\n"
        "Выберите, куда применить режим:"
    )
    await answer(event, text, reply_markup=modes_root_kb())
    if is_cb:
        await event.answer()



@router.callback_query(F.data == "profiles:account")
async def cb_profiles_account(call: CallbackQuery) -> None:

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)
        current = await get_profile_code(session, user.id)

    if not is_active(sub):
        await edit_message_text(
            call,
            "⛔️ Режимы доступны только при активной подписке.",
            reply_markup=nav_kb(back_cb="buy", home_cb="back"),
        )
        await call.answer()
        return

    allowed = _allowed_profiles(sub.plan_code)
    await _render_account_modes(call, current=current, allowed=allowed)
    await call.answer()


@router.callback_query(F.data == "profiles:device")
async def cb_profiles_device(call: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)
        devices = await list_devices(session, user.id)

    if not is_active(sub):
        await edit_message_text(
            call,
            "⛔️ Режимы доступны только при активной подписке.",
            reply_markup=nav_kb(back_cb="buy", home_cb="back"),
        )
        await call.answer()
        return

    items = [
        (d.id, f"{type_title(d.device_type)} {h(d.label or '')}".strip())
        for d in devices
        if d.status != "deleted"
    ]
    if not items:
        await edit_message_text(
            call,
            "У вас пока нет устройств. Сначала добавьте устройство.",
            reply_markup=nav_kb(back_cb="profiles", home_cb="back"),
        )
        await call.answer()
        return

    await edit_message_text(
        call,
        "📱 <b>Выберите устройство</b>, чтобы применить режим:",
        reply_markup=profiles_device_list_kb(items),
    )
    await call.answer()


@router.callback_query(F.data.startswith("profiles:device:"))
async def cb_profiles_device_modes(call: CallbackQuery) -> None:
    device_id = int(call.data.split(":")[-1])

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)
        device = await get_device(session, device_id, user_id=user.id)

    if not is_active(sub):
        await edit_message_text(
            call,
            "⛔️ Режимы доступны только при активной подписке.",
            reply_markup=nav_kb(back_cb="buy", home_cb="back"),
        )
        await call.answer()
        return

    if not device or device.status == "deleted":
        await call.answer("Устройство не найдено", show_alert=True)
        return

    await _render_device_modes(call, device=device, sub=sub)
    await call.answer()


@router.callback_query(F.data.startswith("profile_apply:account:"))
async def cb_apply_to_account(call: CallbackQuery) -> None:
    code = call.data.split(":")[-1]

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return
        sub = await get_or_create_subscription(session, user.id)
        if not is_active(sub):
            await call.answer("Подписка не активна", show_alert=True)
            return

        allowed = _allowed_profiles(sub.plan_code)
        if code not in allowed:
            await call.answer("Недоступно на вашем тарифе", show_alert=True)
            return

        await set_profile_code(session, user.id, code)

    await _render_account_modes(call, current=code, allowed=allowed)
    await call.answer("✅ Применено")


@router.callback_query(F.data.startswith("profile_apply:device:"))
async def cb_apply_to_device(call: CallbackQuery) -> None:
    _, _, device_id_s, code = call.data.split(":", 3)
    device_id = int(device_id_s)

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)
        if not is_active(sub):
            await call.answer("Подписка не активна", show_alert=True)
            return

        allowed = _allowed_profiles(sub.plan_code)
        if code not in allowed:
            await call.answer("Недоступно на вашем тарифе", show_alert=True)
            return

        device = await get_device(session, device_id, user_id=user.id)
        if not device or device.status == "deleted":
            await call.answer("Устройство не найдено", show_alert=True)
            return

        if code not in {p[0] for p in PROFILES}:
            await call.answer("Неизвестный режим", show_alert=True)
            return


        device = await set_device_profile(session, device, code)

    await _render_device_modes(call, device=device, sub=sub)
    await call.answer("✅ Применено")


async def _render_device_modes(call: CallbackQuery, *, device, sub) -> None:
    allowed = _allowed_profiles(sub.plan_code)
    current = device.profile_code

    text = (
        f"📱 <b>{h(type_title(device.device_type))} {h(device.label or '')}</b>\n\n"
        f"Текущий режим: <b>{h(current or '—')}</b>\n\n"
        "Выберите режим ниже:"
    )
    await edit_message_text(call, text, reply_markup=profiles_device_modes_kb(device.id, current, allowed=allowed))


async def _render_account_modes(call: CallbackQuery, *, current: str | None, allowed: set[str]) -> None:
    text = (
        "👤 <b>Режимы для аккаунта</b>\n\n"
        f"Текущий режим: <b>{h(current or '—')}</b>\n\n"
        "Выберите режим ниже:"
    )
    await edit_message_text(call, text, reply_markup=profiles_account_kb(current, allowed=allowed))
