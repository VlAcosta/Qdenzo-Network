# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Subscription, User
from .catalog import PlanOption, TRIAL_HOURS, get_plan_option


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def get_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    q = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
    return q.scalar_one_or_none()


async def get_or_create_subscription(session: AsyncSession, user_id: int) -> Subscription:
    sub = await get_subscription(session, user_id)
    if sub:
        return sub

    # Default subscription record for a new user.
    # Not active until expires_at is set.
    trial_opt = get_plan_option('trial', 0)
    sub = Subscription(
        user_id=user_id,
        plan_code=trial_opt.code,
        devices_limit=trial_opt.devices_limit,
        trial_used=False,
        started_at=None,
        expires_at=None,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


def is_active(sub: Subscription | None) -> bool:
    if not sub or not sub.expires_at:
        return False
    return sub.expires_at > now_utc()


async def activate_trial(session: AsyncSession, user: User) -> tuple[bool, str]:
    """Activate a one-time trial for the user.

    Returns: (ok, reason)
    """
    sub = await get_or_create_subscription(session, user.id)

    if sub.trial_used:
        return False, "Trial уже был использован."

    # If user already has an active paid plan, do not allow trial.
    if is_active(sub) and sub.plan_code != 'trial':
        return False, "У вас уже есть активная подписка."

    trial_opt = get_plan_option('trial', 0)

    sub.plan_code = trial_opt.code
    sub.devices_limit = trial_opt.devices_limit
    sub.started_at = now_utc()
    sub.expires_at = now_utc() + timedelta(hours=TRIAL_HOURS)
    sub.trial_used = True

    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return True, "Trial активирован."


async def apply_plan_purchase(session: AsyncSession, user: User, opt: PlanOption) -> datetime:
    """Apply a paid plan purchase/renewal.

    Extends existing subscription if it is active, otherwise starts from now.

    Returns the new expires_at value (UTC datetime).
    """
    sub = await get_or_create_subscription(session, user.id)

    start_from = sub.expires_at if is_active(sub) and sub.expires_at else now_utc()
    new_expires = start_from + timedelta(days=opt.duration_days)

    sub.plan_code = opt.code
    sub.devices_limit = opt.devices_limit
    if not sub.started_at or not is_active(sub):
        sub.started_at = now_utc()
    sub.expires_at = new_expires

    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return new_expires


async def apply_purchase(session: AsyncSession, user: User, plan_code: str, months: int) -> datetime:
    """Compatibility helper: apply purchase by plan_code/months."""
    opt = get_plan_option(plan_code, months)
    return await apply_plan_purchase(session, user, opt)
