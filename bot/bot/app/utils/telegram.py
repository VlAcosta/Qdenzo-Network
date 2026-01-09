from __future__ import annotations

from typing import Any

from aiogram.types import CallbackQuery, Message


async def edit_message_text(event: CallbackQuery | Message, text: str, reply_markup: Any = None) -> None:
    message = event.message if isinstance(event, CallbackQuery) else event

    if message.text is not None:
        await message.edit_text(text, reply_markup=reply_markup)
        return
    if message.caption is not None:
        await message.edit_caption(caption=text, reply_markup=reply_markup)
        return

    await message.answer(text, reply_markup=reply_markup)


async def safe_answer(call: CallbackQuery, **kwargs: Any) -> None:
    """Answer callback safely (ignore expired queries)."""
    try:
        await call.answer(**kwargs)
    except Exception:
        return