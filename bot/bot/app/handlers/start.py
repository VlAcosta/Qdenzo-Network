# -*- coding: utf-8 -*-

from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram import Router

from ..config import settings
from ..db import session_scope
from ..keyboards.main import main_menu
from ..keyboards.onboarding import onboarding_continue_kb, onboarding_finish_kb, onboarding_start_kb
from ..services.subscriptions import is_active
from ..services import get_or_create_subscription
from ..services.users import ensure_user
from ..utils.text import h
from ..utils.telegram import edit_message_text, safe_answer_callback, send_html, send_html_with_photo

router = Router()


def _parse_ref(message: Message) -> str | None:
    if not message.text:
        return None
    if " " not in message.text:
        return None
    _, arg = message.text.split(" ", 1)
    if arg.startswith("ref_"):
        return arg.replace("ref_", "", 1)
    return None

def _main_menu_text(user) -> str:
    return (
        "<b>Главное меню</b>\n\n"
        f"ID: <code>{user.tg_id}</code>\n"
        f"Баланс: <b>{user.balance_rub} ₽</b>\n\n"
        "Выберите действие ниже 👇"
    )

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    ref = _parse_ref(message)

    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user, ref_code=ref)
        if user.is_banned:
            await message.answer(
                "⛔️ Доступ к боту ограничен.\n"
                "Если это ошибка — напишите в поддержку: " + h(settings.support_username)
            )
            return

        sub = await get_or_create_subscription(session, user.id)
        has_sub = is_active(sub)
    if ref is None and not user.onboarding_done:
        text = (
            "Добро пожаловать в <b>Qdenzo Network</b> 👋\n\n"
            "Это частная сеть для стабильного и безопасного доступа\n"
            "к интернету с быстрым подключением и понятными настройками.\n\n"
            "Запуск займёт меньше минуты.\n"
            "Нажмите «Старт», чтобы продолжить."
        )
        photo_path = settings.start_photo_path
        if photo_path:
            try:
                photo = FSInputFile(str(photo_path))
                await message.answer_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=onboarding_start_kb(),
                    parse_mode="HTML",
                )
                return
            except Exception:
                pass
        await send_html(message, text, reply_markup=onboarding_start_kb())
        return
    photo_path = settings.start_photo_path
    if photo_path:
        try:
            photo = FSInputFile(str(photo_path))
            await message.answer_photo(
                photo=photo,
                caption=_main_menu_text(user),
                reply_markup=main_menu(user.is_admin, has_subscription=has_sub),
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    await send_html(
        message,
        _main_menu_text(user),
        reply_markup=main_menu(user.is_admin, has_subscription=has_sub),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=message.from_user)
        sub = await get_or_create_subscription(session, user.id)

    await send_html_with_photo(
        message,
        _main_menu_text(user),
        reply_markup=main_menu(user.is_admin, has_subscription=is_active(sub)),
        photo_path=settings.start_photo_path,
    )



@router.callback_query(F.data == "onb:2")
async def cb_onboarding_step2(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    text = (
        "Qdenzo Network — частная сеть для стабильного доступа\n"
        "без лишних настроек и сложных инструкций.\n\n"
        "Подключение занимает пару шагов,\n"
        "а перед оплатой можно оценить качество сервиса."
    )
    await edit_message_text(call, text, reply_markup=onboarding_continue_kb())


@router.callback_query(F.data == "onb:3")
async def cb_onboarding_step3(call: CallbackQuery) -> None:
    await safe_answer_callback(call)
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        sub = await get_or_create_subscription(session, user.id)
        include_trial = not sub.trial_used
    text = (
        "Вы можете попробовать сервис бесплатно\n"
        "или перейти сразу в главное меню.\n\n"
        "Бесплатный период поможет оценить\n"
        "стабильность и скорость подключения."
    )
    await edit_message_text(call, text, reply_markup=onboarding_finish_kb(include_trial=include_trial))
    async with session_scope() as session:
        user = await ensure_user(session=session, tg_user=call.from_user)
        user.onboarding_done = True
        session.add(user)
        await session.commit()