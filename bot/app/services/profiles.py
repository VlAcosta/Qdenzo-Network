# -*- coding: utf-8 -*-

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Device, User
from .subscriptions import now_utc


async def get_profile_code(session: AsyncSession, user_id: int) -> str:
    q = await session.execute(select(User.profile_code).where(User.id == user_id))
    code = q.scalar_one_or_none()
    return code or 'smart'


async def set_profile_code(session: AsyncSession, user_id: int, code: str) -> None:
    user = await session.get(User, user_id)
    if not user:
        return
    user.profile_code = code
    user.profile_updated_at = now_utc()
    session.add(user)
    devices = await session.execute(select(Device).where(Device.user_id == user_id))
    for device in devices.scalars().all():
        device.profile_code = code
        device.updated_at = now_utc()
        session.add(device)
    await session.commit()
