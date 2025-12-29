# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from .config import settings
from .db import init_db

# Handlers
from .handlers.start import router as start_router
from .handlers.buy import router as buy_router
from .handlers.subscription import router as sub_router
from .handlers.devices import router as dev_router
from .handlers.profiles import router as profiles_router
from .handlers.traffic import router as traffic_router
from .handlers.referrals import router as ref_router
from .handlers.support import router as support_router
from .handlers.faq import router as faq_router
from .handlers.admin import router as admin_router
from .handlers.fallback import router as fallback_router


def _build_dp() -> Dispatcher:
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    # Order matters: more specific first
    dp.include_router(start_router)
    dp.include_router(buy_router)
    dp.include_router(sub_router)
    dp.include_router(dev_router)
    dp.include_router(profiles_router)
    dp.include_router(traffic_router)
    dp.include_router(ref_router)
    dp.include_router(support_router)
    dp.include_router(faq_router)
    dp.include_router(admin_router)
    dp.include_router(fallback_router)
    return dp


async def main() -> None:
    logger.info('Starting {brand} bot...', brand=settings.brand_name)
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dp()

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
