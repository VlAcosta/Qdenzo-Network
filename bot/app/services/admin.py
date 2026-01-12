# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Device, Order, Subscription, User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def get_dashboard_stats(session: AsyncSession) -> dict[str, int]:
    now = _now_utc()
    last_24h = now - timedelta(hours=24)
    last_30d = now - timedelta(days=30)

    total_users = await session.scalar(select(func.count(User.id)))
    active_subs = await session.scalar(
        select(func.count(Subscription.id)).where(Subscription.expires_at > now)
    )
    new_users_24h = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= last_24h)
    )
    pending_orders = await session.scalar(
        select(func.count(Order.id)).where(Order.status == "pending")
    )
    active_devices = await session.scalar(
        select(func.count(Device.id)).where(Device.status == "active")
    )
    revenue_24h = await session.scalar(
        select(func.coalesce(func.sum(Order.amount_rub), 0)).where(
            Order.status == "paid",
            Order.paid_at.is_not(None),
            Order.paid_at >= last_24h,
        )
    )
    revenue_30d = await session.scalar(
        select(func.coalesce(func.sum(Order.amount_rub), 0)).where(
            Order.status == "paid",
            Order.paid_at.is_not(None),
            Order.paid_at >= last_30d,
        )
    )

    return {
        "total_users": int(total_users or 0),
        "active_subs": int(active_subs or 0),
        "new_users_24h": int(new_users_24h or 0),
        "pending_orders": int(pending_orders or 0),
        "active_devices": int(active_devices or 0),
        "revenue_24h": int(revenue_24h or 0),
        "revenue_30d": int(revenue_30d or 0),
    }


async def get_plan_distribution(session: AsyncSession) -> list[tuple[str, int]]:
    q = await session.execute(
        select(Subscription.plan_code, func.count(Subscription.id))
        .group_by(Subscription.plan_code)
        .order_by(func.count(Subscription.id).desc())
    )
    return [(row[0], int(row[1])) for row in q.all()]


async def find_user(session: AsyncSession, query: str) -> User | None:
    query = query.strip()
    if not query:
        return None
    if query.startswith("@"):
        query = query[1:]
    if query.isdigit():
        return await session.scalar(select(User).where(User.tg_id == int(query)))
    return await session.scalar(select(User).where(User.username == query))


async def get_user_orders(session: AsyncSession, user_id: int, limit: int = 5) -> list[Order]:
    q = await session.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(q.scalars().all())


async def get_user_devices(session: AsyncSession, user_id: int) -> list[Device]:
    q = await session.execute(select(Device).where(Device.user_id == user_id).order_by(Device.created_at.desc()))
    return list(q.scalars().all())


async def list_recent_orders(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Order.status == status)
    q = await session.execute(stmt)
    return list(q.scalars().all())


async def list_pending_orders_older_than(
    session: AsyncSession,
    *,
    older_than: timedelta,
    limit: int = 50,
) -> list[Order]:
    threshold = _now_utc() - older_than
    q = await session.execute(
        select(Order)
        .where(Order.status == "pending", Order.created_at < threshold)
        .order_by(Order.created_at.asc())
        .limit(limit)
    )
    return list(q.scalars().all())


async def list_expiring_subscriptions(
    session: AsyncSession,
    *,
    within_days: int,
) -> list[tuple[Subscription, User]]:
    now = _now_utc()
    target = now + timedelta(days=within_days)
    q = await session.execute(
        select(Subscription, User)
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.expires_at.is_not(None), Subscription.expires_at <= target, Subscription.expires_at > now)
        .order_by(Subscription.expires_at.asc())
    )
    return list(q.all())


def chunked(items: Iterable, size: int) -> list[list]:
    bucket: list[list] = []
    current: list = []
    for item in items:
        current.append(item)
        if len(current) >= size:
            bucket.append(current)
            current = []
    if current:
        bucket.append(current)
    return bucket