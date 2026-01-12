# -*- coding: utf-8 -*-

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User


def _new_ref_code() -> str:
    # short url-safe code
    return secrets.token_urlsafe(8).replace('-', '').replace('_', '')[:12]


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    q = await session.execute(select(User).where(User.tg_id == tg_id))
    return q.scalar_one_or_none()


async def get_user_by_ref_code(session: AsyncSession, code: str) -> User | None:
    q = await session.execute(select(User).where(User.referral_code == code))
    return q.scalar_one_or_none()


async def get_or_create_user(
    *,
    session: AsyncSession,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    ref_code: str | None,
    locale: str | None,
) -> User:
    user = await get_user_by_tg_id(session, tg_id)
    if user:
        # update profile fields
        user.username = username
        user.first_name = first_name
        user.locale = locale
        user.is_admin = tg_id in settings.admin_id_list
        session.add(user)
        await session.commit()
        return user

    inviter_id = None
    if ref_code:
        inviter = await get_user_by_ref_code(session, ref_code)
        if inviter:
            inviter_id = inviter.id

    # ensure unique referral code
    ref = _new_ref_code()
    # try a few times
    for _ in range(5):
        existing = await get_user_by_ref_code(session, ref)
        if not existing:
            break
        ref = _new_ref_code()

    user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        created_at=datetime.now(timezone.utc),
        is_admin=(tg_id in settings.admin_id_list),
        is_banned=False,
        inviter_id=inviter_id,
        referral_code=ref,
        locale=locale,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

async def ensure_user(
    *,
    session: AsyncSession,
    tg_user,
    ref_code: str | None = None,
) -> User:
    """Wrapper to ensure required fields are always provided."""
    return await get_or_create_user(
        session=session,
        tg_id=tg_user.id,
        username=getattr(tg_user, "username", None),
        first_name=getattr(tg_user, "first_name", None) or "",
        ref_code=ref_code,
        locale=getattr(tg_user, "language_code", None) or "ru",
    )
