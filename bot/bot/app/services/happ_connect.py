from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .happ_crypto import encrypt_subscription_url  # твоя функция шифрования
from ..config import settings


def happ_connect_kb(*, plain_url: str, crypt_url: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if crypt_url:
        kb.button(text="🚀 Добавить в Happ", url=crypt_url)

    kb.button(text="⬇️ Установить Happ", url="https://www.happ.su/")
    kb.button(text="🔗 Обычная ссылка", url=plain_url)

    # Если хочешь ссылку на инструкцию:
    # kb.button(text="📄 Инструкция", url="https://www.happ.su/....")
    # Или сделай callback и покажи инструкцию текстом:
    kb.button(text="📄 Инструкция", callback_data="happ:help")

    kb.adjust(1)
    return kb.as_markup()


async def build_happ_urls(subscription_url: str) -> tuple[str, str | None]:
    """
    Возвращает (plain_url, crypt_url|None).
    crypt_url вида happ://crypt3/...
    """
    plain_url = subscription_url.strip()

    try:
        crypt_url = await encrypt_subscription_url(plain_url)
    except Exception:
        crypt_url = None

    return plain_url, crypt_url
