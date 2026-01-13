# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..marzban.client import MarzbanClient
from ..models import Order, User
from .catalog import get_plan_option
from .payments.common import load_order_meta
from .devices import enforce_device_limit, sync_devices_expire
from .referrals import maybe_grant_referral_bonus
from .subscriptions import apply_plan_purchase, get_or_create_subscription, is_active, now_utc


async def create_subscription_order(
    session: AsyncSession,
    user_id: int,
    plan_code: str,
    months: int,
    amount_rub: int | None = None,
    payment_method: str = 'manual',
    provider: str | None = None,
    action: str | None = None,
    meta: dict | None = None,
) -> Order:
    opt = get_plan_option(plan_code, months)
    final_amount = opt.price_rub if amount_rub is None else amount_rub
    order = Order(
        user_id=user_id,
        kind='subscription',
        plan_code=plan_code,
        months=months,
        amount_rub=final_amount,
        currency='RUB',
        payment_method=payment_method,
        provider=provider or payment_method,
        status='pending',
        created_at=now_utc(),
    )
    if meta:
        order.meta_json = json.dumps(meta, ensure_ascii=False)
    if action:
        payload = {"action": action}
        if order.meta_json:
            payload.update(load_order_meta(order))
        order.meta_json = json.dumps(payload, ensure_ascii=False)
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    q = await session.execute(select(Order).where(Order.id == order_id))
    return q.scalar_one_or_none()


async def list_pending_orders(session: AsyncSession, limit: int = 20) -> list[Order]:
    q = await session.execute(
        select(Order).where(Order.status == 'pending').order_by(desc(Order.id)).limit(limit)
    )
    return list(q.scalars().all())


async def mark_order_paid(
    *,
    session: AsyncSession,
    marz: MarzbanClient,
    order: Order,
) -> tuple[datetime, list[str]]:
    """Mark as paid and apply subscription + referral bonus.

    Returns:
      (new_expires_at, notes)
    """
    if order.status == 'paid':
        sub = await get_or_create_subscription(session, order.user_id)
        return sub.expires_at or now_utc(), ['already_paid']

    user_q = await session.execute(select(User).where(User.id == order.user_id))
    user = user_q.scalar_one()

    opt = get_plan_option(order.plan_code, order.months)
    sub = await get_or_create_subscription(session, user.id)

    # Apply subscription
    new_exp = await apply_plan_purchase(session, user, opt)

    # Update Marzban users expire
    expire_ts = int(new_exp.timestamp())
    await sync_devices_expire(session=session, marz=marz, user_id=user.id, expire_ts=expire_ts)

    # Enforce device limit (disable extras)
    disabled = await enforce_device_limit(session=session, marz=marz, user_id=user.id, limit=opt.devices_limit)

    # Update order
    order.status = 'paid'
    order.paid_at = now_utc()
    session.add(order)
    await session.commit()

    notes: list[str] = []
    if disabled:
        notes.append(f"disabled_{len(disabled)}_devices")

    # Referral bonus for inviter (if any)
    bonus_applied = await maybe_grant_referral_bonus(session=session, referral_user_id=user.id, order=order)
    if bonus_applied:
        notes.append(f"ref_bonus={bonus_applied}s")

    # Promo redemption (if any)
    from .promos import redeem_promo_for_order
    try:
        redeemed = await redeem_promo_for_order(session=session, order=order, user_id=user.id)
    except Exception:
        redeemed = False
    if redeemed:
        notes.append("promo_redeemed")

    return new_exp, notes

async def cancel_order(session: AsyncSession, order_id: int) -> Order | None:
    """Cancel pending order (manual payments)."""
    order = await get_order(session, order_id)
    if not order:
        return None
    if order.status != 'pending':
        return order
    order.status = 'canceled'
    session.add(order)
    await session.commit()
    return order
