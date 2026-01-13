# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Promo, PromoRedemption
from .payments.common import load_order_meta


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


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
    promo = Promo(
        code=normalize_code(code),
        discount_rub=discount_rub,
        max_uses=max_uses,
        used_count=0,
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def toggle_promo(session: AsyncSession, promo_id: int) -> Promo | None:
    q = await session.execute(select(Promo).where(Promo.id == promo_id))
    promo = q.scalar_one_or_none()
    if not promo:
        return None
    promo.active = not promo.active
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def delete_promo(session: AsyncSession, promo_id: int) -> bool:
    q = await session.execute(select(Promo).where(Promo.id == promo_id))
    promo = q.scalar_one_or_none()
    if not promo:
        return False
    await session.delete(promo)
    await session.commit()
    return True


async def promo_available_for_user(
    session: AsyncSession,
    *,
    code: str,
    user_id: int,
) -> tuple[Promo | None, str | None]:
    promo = await get_promo_by_code(session, code)
    if not promo or not promo.active:
        return None, "Промокод не найден или больше недоступен."
    if promo.max_uses and promo.used_count >= promo.max_uses:
        return None, "Промокод не найден или больше недоступен."
    q = await session.execute(
        select(PromoRedemption).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    )
    if q.scalar_one_or_none():
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
    return True