# -*- coding: utf-8 -*-

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import session_scope
from ..keyboards.profiles import PROFILES, profile_apply_kb, profile_devices_kb, profiles_kb, profile_descr
from ..services.devices import list_devices
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
        current = await get_profile_code(session, user.id)

    if not is_active(sub):
        text = (
            "⛔️ <b>Режимы доступны только при активной подписке.</b>\n\n"
            "Оформите тариф в разделе <b>Купить</b> / <b>Управление</b>."
        )
        await answer(event, text)
        if is_cb:
            await event.answer()
        return

    allowed = _allowed_profiles(sub.plan_code)

    text = (
        "🧠 <b>Режимы — профили использования</b>\n\n"
        f"Текущий: <b>{h(current or '—')}</b>\n\n"
        "Выберите режим ниже:"
    )
    await answer(event, text, reply_markup=profiles_kb(current, allowed=allowed))
    if is_cb:
        await event.answer()


@router.callback_query(F.data.startswith("profile:"))
async def cb_profile(call: CallbackQuery) -> None:
    code = call.data.split(":", 1)[1]

    async with session_scope() as session:
        user = await get_user_by_tg_id(session, call.from_user.id)
        if not user:
            await call.answer("Сначала /start", show_alert=True)
            return

        sub = await get_or_create_subscription(session, user.id)
        current = await get_profile_code(session, user.id)

    if not is_active(sub):
        await edit_message_text(call, "⛔️ Режимы доступны только при активной подписке.")
        await call.answer()
        return

    allowed = _allowed_profiles(sub.plan_code)
    descr = profile_descr(code)

    if code not in allowed:
        await edit_message_text(
            call,
            "🔒 <b>Режим недоступен для вашего тарифа.</b>\n\n"
            f"Режим: <b>{h(code)}</b>\n"
            f"Описание: {h(descr)}\n\n"
            "Перейдите в <b>Управление → Подписка</b>, чтобы открыть этот режим.",
            reply_markup=profiles_kb(current, allowed=allowed),
        )
        await call.answer()
        return

    text = (
        f"🧠 <b>{h(code)}</b>\n\n"
        f"{h(descr)}\n\n"
        "Применить режим:"
    )
    await edit_message_text(call, text, reply_markup=profile_apply_kb(code))
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

    await call.answer("✅ Применено")
    await show_profiles(call)


@router.callback_query(F.data.startswith("profile_apply:device:"))
async def cb_apply_to_device(call: CallbackQuery) -> None:
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

        devices = await list_devices(session, user.id)

    items = [(d.id, f"{d.label or 'Устройство'}") for d in devices if d.status != "deleted"]
    if not items:
        await call.answer("Сначала добавьте устройство", show_alert=True)
        return

    await edit_message_text(
        call,
        "📱 <b>Выберите устройство</b>, чтобы применить режим:",
        reply_markup=profile_devices_kb(code, items),
    )
    await call.answer()
