from __future__ import annotations

from typing import Any
from aiogram.exceptions import TelegramBadRequest

from aiogram.types import CallbackQuery, Message

def _markup_payload(markup: Any | None) -> dict | None:
    if not markup:
        return None
    try:
        return markup.model_dump()
    except Exception:
        return None


def _same_markup(a: Any | None, b: Any | None) -> bool:
    return _markup_payload(a) == _markup_payload(b)


async def safe_edit_text(message: Message, text: str, reply_markup: Any = None, parse_mode: str | None = None) -> None:
    if message.text == text and _same_markup(message.reply_markup, reply_markup):
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc) or "message to edit not found" in str(exc):
            return
        raise


async def safe_edit_caption(
    message: Message,
    caption: str,
    reply_markup: Any = None,
    parse_mode: str | None = None,
) -> None:
    if message.caption == caption and _same_markup(message.reply_markup, reply_markup):
        return
    try:
        await message.edit_caption(caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc) or "message to edit not found" in str(exc):
            return
        raise


async def edit_message_text(
    event: CallbackQuery | Message,
    text: str,
    reply_markup: Any = None,
    parse_mode: str | None = "HTML",
) -> None:
    message = event.message if isinstance(event, CallbackQuery) else event

    if message.text is not None:
        await safe_edit_text(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    if message.caption is not None:
        await safe_edit_caption(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return

    await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def safe_answer(call: CallbackQuery, **kwargs: Any) -> None:
    """Answer callback safely (ignore expired queries)."""
    try:
        await call.answer(**kwargs)
    except Exception:
        return


async def safe_answer_callback(call: CallbackQuery, text: str | None = None, **kwargs: Any) -> None:
    """Answer callback safely (ignore expired/duplicate queries)."""
    payload = kwargs.copy()
    if text is not None:
        payload["text"] = text
    try:
        await call.answer(**payload)
    except Exception:
        return


async def send_html(message_or_call: Message | CallbackQuery, text: str, reply_markup: Any = None) -> None:
    """Send a new message with HTML parse mode."""
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message_or_call.answer(text, reply_markup=reply_markup, parse_mode="HTML")