# -*- coding: utf-8 -*-

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order, ReferralEvent, ReferralWindow, Subscription, User
from .subscriptions import get_or_create_subscription, is_active, now_utc

DAY = 24 * 3600
HOUR = 3600

WINDOW_DAYS = 30
CAP_DAYS = 15
WINDOW_SECONDS = WINDOW_DAYS * DAY
CAP_SECONDS = CAP_DAYS * DAY

BONUS_MATRIX: dict[tuple[str, int], dict[str, int]] = {
    ("start", 1): {"start": 1 * DAY, "pro": 12 * HOUR, "family": 3 * HOUR},
    ("start", 3): {"start": 36 * HOUR, "pro": 12 * HOUR, "family": 6 * HOUR},
    ("start", 6): {"start": 3 * DAY, "pro": 2 * DAY, "family": 1 * DAY},

    ("pro", 1): {"start": 2 * DAY, "pro": 1 * DAY, "family": 12 * HOUR},
    ("pro", 3): {"start": 2 * DAY, "pro": 1 * DAY, "family": 12 * HOUR},
    ("pro", 6): {"start": 3 * DAY, "pro": 2 * DAY, "family": 1 * DAY},

    ("family", 3): {"start": 5 * DAY, "pro": 3 * DAY, "family": 2 * DAY},
    ("family", 12): {"start": 7 * DAY, "pro": 5 * DAY, "family": 3 * DAY},
}


def _inviter_tier(sub: Subscription) -> str:
    if not is_active(sub):
        return "start"
    if sub.plan_code in ("pro", "family", "start"):
        return sub.plan_code
    return "start"


def _months_key(plan_code: str, months: int) -> int:
    if plan_code in ("start", "pro"):
        return 6 if months in (6, 12) else months
    if plan_code == "family":
        return 3 if months in (3, 6) else months
    return months


async def get_referral_summary(session: AsyncSession, inviter_id: int) -> tuple[int, int, ReferralWindow | None]:
    q = await session.execute(select(User).where(User.inviter_id == inviter_id))
    invited_count = len(list(q.scalars().all()))

    q2 = await session.execute(
        select(ReferralEvent).where(
            ReferralEvent.inviter_id == inviter_id,
            ReferralEvent.reversed_at.is_(None),
        )
    )
    total = sum(e.applied_seconds for e in q2.scalars().all())

    window = await session.get(ReferralWindow, inviter_id)
    return invited_count, total, window


async def maybe_grant_referral_bonus(*, session: AsyncSession, referral_user_id: int, order: Order) -> int:
    if order.kind != "subscription":
        return 0
    if order.status != "paid":
        return 0

    q = await session.execute(select(User).where(User.id == referral_user_id))
    referral_user = q.scalar_one_or_none()
    if not referral_user or not referral_user.inviter_id:
        return 0

    inviter_id = referral_user.inviter_id

    q_ev = await session.execute(select(ReferralEvent).where(ReferralEvent.order_id == order.id))
    if q_ev.scalar_one_or_none():
        return 0

    inviter_sub = await get_or_create_subscription(session, inviter_id)
    tier = _inviter_tier(inviter_sub)

    if inviter_sub.plan_code not in ("start", "pro", "family") or inviter_sub.plan_code == "trial" or not is_active(inviter_sub):
        tier = "start"

    mk = _months_key(order.plan_code, int(order.months))
    bonus_seconds = BONUS_MATRIX.get((order.plan_code, mk), {}).get(tier, 0)
    if bonus_seconds <= 0:
        return 0

    now = now_utc()

    window = await session.get(ReferralWindow, inviter_id)
    if not window or not window.window_end_at or window.window_end_at <= now:
        window = ReferralWindow(
            inviter_id=inviter_id,
            window_start_at=now,
            window_end_at=now + timedelta(days=WINDOW_DAYS),
            applied_seconds=0,
        )
        session.add(window)
        await session.flush()

    remaining = CAP_SECONDS - int(window.applied_seconds)
    applied = max(0, min(int(bonus_seconds), int(remaining)))

    ev = ReferralEvent(
        inviter_id=inviter_id,
        referral_user_id=referral_user_id,
        order_id=order.id,
        bonus_seconds=int(bonus_seconds),
        applied_seconds=int(applied),
        created_at=now,
    )
    session.add(ev)

    if applied > 0:
        sub = await get_or_create_subscription(session, inviter_id)
        base = sub.expires_at if is_active(sub) else now
        sub.expires_at = base + timedelta(seconds=applied)

        if sub.plan_code not in ("start", "pro", "family") or sub.plan_code == "trial":
            sub.plan_code = "start"
            sub.devices_limit = 3

        window.applied_seconds = int(window.applied_seconds) + int(applied)
        session.add(sub)
        session.add(window)

    await session.commit()
    return int(applied)


async def rollback_referral_bonus_for_order(session: AsyncSession, order_id: int, reason: str = "rollback") -> int:
    q = await session.execute(
        select(ReferralEvent).where(
            ReferralEvent.order_id == order_id,
            ReferralEvent.reversed_at.is_(None),
        )
    )
    ev = q.scalar_one_or_none()
    if not ev or ev.applied_seconds <= 0:
        return 0

    now = now_utc()
    inviter_id = ev.inviter_id
    applied = int(ev.applied_seconds)

    sub = await get_or_create_subscription(session, inviter_id)
    if sub.expires_at:
        new_exp = sub.expires_at - timedelta(seconds=applied)
        if new_exp < now:
            new_exp = now
        sub.expires_at = new_exp
        session.add(sub)

    window = await session.get(ReferralWindow, inviter_id)
    if window and window.window_start_at and window.window_end_at and window.window_start_at <= ev.created_at <= window.window_end_at:
        window.applied_seconds = max(0, int(window.applied_seconds) - applied)
        session.add(window)

    ev.reversed_at = now
    ev.reversal_reason = reason
    session.add(ev)

    await session.commit()
    return applied


async def get_referral_stats(session: AsyncSession, inviter_id: int) -> dict:
    """
    ВАЖНО: handler referrals.py ожидает ключи window_applied_seconds / cap_seconds.
    Мы возвращаем и "новые" (applied_seconds), и "совместимые".
    """
    now = now_utc()

    q = await session.execute(select(User.id).where(User.inviter_id == inviter_id))
    invited = q.scalars().all()
    invited_count = len(invited)

    window = await session.get(ReferralWindow, inviter_id)
    if not window or not window.window_end_at or window.window_end_at < now:
        applied = 0
        remaining = CAP_SECONDS
        end_at = None
    else:
        applied = int(window.applied_seconds or 0)
        remaining = max(0, CAP_SECONDS - applied)
        end_at = window.window_end_at

    return {
        "invited_count": invited_count,

        # основное
        "applied_seconds": int(applied),
        "remaining_seconds": int(remaining),
        "window_end_at": end_at,

        # совместимость с текущим handler’ом
        "window_applied_seconds": int(applied),
        "cap_seconds": int(CAP_SECONDS),
    }
