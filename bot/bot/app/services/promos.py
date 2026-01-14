# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Promo, PromoRedemption, User
from .payments.common import load_order_meta
from loguru import logger


PROMO_CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()



def validate_promo_code(code: str) -> tuple[str | None, str | None]:
    normalized = normalize_code(code)
    if not normalized:
        return None, "Введите промокод."
    if len(normalized) < 3 or len(normalized) > 32:
        return None, "Длина промокода должна быть от 3 до 32 символов."
    if not PROMO_CODE_RE.fullmatch(normalized):
        return None, "Промокод может содержать только A-Z, 0-9, '_' и '-' без пробелов."
    return normalized, None


async def get_promo_by_code(session: AsyncSession, code: str) -> Promo | None:
    normalized = normalize_code(code)
    if not normalized:
        return None
    q = await session.execute(select(Promo).where(func.lower(Promo.code) == normalized.lower()))
    return q.scalar_one_or_none()


async def list_promos(session: AsyncSession) -> list[Promo]:
    q = await session.execute(select(Promo).order_by(Promo.id.desc()))
    return list(q.scalars().all())


async def create_promo(
    session: AsyncSession,
    *,
    code: str,
    discount_rub: int,
    max_uses: int,
) -> Promo:
    normalized, error = validate_promo_code(code)
    if error:
        raise ValueError(error)
    async with session.begin():
        promo = Promo(
            code=normalized,
            discount_rub=discount_rub,
            max_uses=max_uses,
            used_count=0,
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        session.add(promo)
    await session.refresh(promo)
    logger.info("Promo created code={} discount={} max_uses={}", promo.code, promo.discount_rub, promo.max_uses)
    return promo


async def toggle_promo(session: AsyncSession, promo_id: int) -> Promo | None:
    async with session.begin():
        q = await session.execute(select(Promo).where(Promo.id == promo_id))
        promo = q.scalar_one_or_none()
        if not promo:
            return None
        promo.active = not promo.active
        session.add(promo)
    await session.refresh(promo)
    logger.info("Promo toggled code={} active={}", promo.code, promo.active)
    return promo


async def delete_promo(session: AsyncSession, promo_id: int) -> bool:
    async with session.begin():
        q = await session.execute(select(Promo).where(Promo.id == promo_id))
        promo = q.scalar_one_or_none()
        if not promo:
            return False
        await session.delete(promo)
    logger.info("Promo deleted code={}", promo.code)
    return True


async def promo_available_for_user(
    session: AsyncSession,
    *,
    code: str,
    user_id: int,
) -> tuple[Promo | None, str | None]:
    promo = await get_promo_by_code(session, code)
    if not promo or not promo.active:
        logger.info("Promo unavailable code={} user_id={}", code, user_id)
        return None, "Промокод не найден или больше недоступен."
    if promo.max_uses and promo.used_count >= promo.max_uses:
        logger.info("Promo exhausted code={} user_id={}", code, user_id)
        return None, "Промокод не найден или больше недоступен."
    q = await session.execute(
        select(PromoRedemption).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    )
    if q.scalar_one_or_none():
        logger.info("Promo already used code={} user_id={}", promo.code, user_id)
        return None, "Промокод не найден или больше недоступен."
    return promo, None


async def redeem_promo_for_order(session: AsyncSession, *, order, user_id: int) -> bool:
    meta = load_order_meta(order)
    promo_id = meta.get("promo_id")
    if not promo_id:
        return False

    q = await session.execute(select(PromoRedemption).where(PromoRedemption.order_id == order.id))
    if q.scalar_one_or_none():
        return False

    promo_q = await session.execute(select(Promo).where(Promo.id == int(promo_id)))
    promo = promo_q.scalar_one_or_none()
    if not promo:
        return False

    redemption = PromoRedemption(
        promo_id=promo.id,
        user_id=user_id,
        order_id=order.id,
        redeemed_at=datetime.now(timezone.utc),
    )
    promo.used_count = (promo.used_count or 0) + 1
    session.add_all([promo, redemption])
    await session.commit()
    logger.info("Promo redeemed for order promo_id={} order_id={}", promo.id, order.id)
    return True


async def redeem_promo_to_balance(session: AsyncSession, *, promo: Promo, user: User) -> int:
    redemption = PromoRedemption(
        promo_id=promo.id,
        user_id=user.id,
        order_id=None,
        redeemed_at=datetime.now(timezone.utc),
    )
    promo.used_count = (promo.used_count or 0) + 1
    user.balance_rub = (user.balance_rub or 0) + promo.discount_rub
    session.add_all([promo, redemption, user])
    await session.commit()
    await session.refresh(user)
    logger.info("Promo redeemed to balance promo_id={} user_id={}", promo.id, user.id)
    return user.balance_rub