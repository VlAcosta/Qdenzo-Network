# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from loguru import logger

from ..marzban.client import MarzbanClient, MarzbanError
from ..models import Device, Subscription, User
from .subscriptions import is_active, now_utc


DEVICE_TYPES = {
    'phone': '📱 Телефон',
    'pc': '💻 ПК',
    'tv': '📺 ТВ',
    'tablet': '📟 Планшет',
    'router': '📡 Роутер',
    'other': '🔧 Другое',
}

def type_title(device_type: str) -> str:
    return DEVICE_TYPES.get(device_type, device_type)

def _marzban_username(tg_id: int, slot: int) -> str:
    # Unique per device
    return f"username_{tg_id}_{slot}"


async def list_devices(session: AsyncSession, user_id: int) -> list[Device]:
    q = await session.execute(select(Device).where(Device.user_id == user_id).order_by(asc(Device.slot)))
    return list(q.scalars().all())


async def get_device(session: AsyncSession, device_id: int, user_id: int | None = None) -> Device | None:
    stmt = select(Device).where(Device.id == device_id)
    if user_id is not None:
        stmt = stmt.where(Device.user_id == user_id)
    q = await session.execute(stmt)
    return q.scalar_one_or_none()


async def count_active_devices(session: AsyncSession, user_id: int) -> int:
    q = await session.execute(
        select(Device).where(Device.user_id == user_id, Device.status == 'active')
    )
    return len(q.scalars().all())


async def next_free_slot(devices: Iterable[Device], limit: int) -> int | None:
    used = {d.slot for d in devices if d.status != 'deleted'}
    for s in range(1, limit + 1):
        if s not in used:
            return s
    return None


async def create_device(
    *,
    session: AsyncSession,
    marz: MarzbanClient,
    user: User,
    sub: Subscription,
    device_type: str,
    label: str,
) -> Device:
    devices = await list_devices(session, user.id)
    slot = await next_free_slot(devices, sub.devices_limit)
    if not slot:
        raise ValueError('devices_limit_reached')

    m_username = _marzban_username(user.tg_id, slot)
    note = f"tg_id={user.tg_id};device_slot={slot};label={label}"

    expire_ts = 0
    status = 'on_hold'
    if sub.expires_at and is_active(sub):
        expire_ts = int(sub.expires_at.replace(tzinfo=timezone.utc).timestamp())
        status = 'active'

    try:
        m_user = await marz.create_user(
            username=m_username,
            expire=expire_ts,
            status=status,
            note=note,
            # if you want to restrict to a specific inbound set tags in MARZBAN_INBOUNDS_JSON
            # inbounds=settings.marzban_inbounds,
        )
    except MarzbanError as exc:
        logger.warning(
            "Marzban create_user failed for tg_id=%s device_type=%s: %s",
            user.tg_id,
            device_type,
            exc,
        )
        raise

    device = Device(
        user_id=user.id,
        slot=slot,
        device_type=device_type,
        label=label,
        status=status,
        profile_code=user.profile_code or 'smart',
        marzban_username=m_username,
        marzban_user_id=str(m_user.get('id') or ''),
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    user.last_device_id = device.id
    user.last_device_type = device.device_type
    user.last_device_label = device.label
    session.add(user)
    await session.commit()

    return device


async def rename_device(session: AsyncSession, device: Device, new_label: str) -> Device:
    device.label = new_label
    device.updated_at = now_utc()
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device

async def set_device_profile(session: AsyncSession, device: Device, code: str) -> Device:
    device.profile_code = code
    device.updated_at = now_utc()
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device



async def set_device_status(
    *,
    session: AsyncSession,
    marz: MarzbanClient,
    device: Device,
    status: str,
) -> Device:
    # status: active/disabled/deleted
    device.status = status
    device.updated_at = now_utc()
    session.add(device)
    await session.commit()

    if device.marzban_username:
        try:
            if status == 'disabled':
                await marz.update_user(device.marzban_username, status='disabled')
            elif status == 'active':
                await marz.update_user(device.marzban_username, status='active')
            elif status == 'deleted':
                # Keep in Marzban but disable
                await marz.update_user(device.marzban_username, status='disabled')
        except Exception:
            # Do not crash UX
            pass

    await session.refresh(device)
    return device


async def sync_devices_expire(
    *,
    session: AsyncSession,
    marz: MarzbanClient,
    user_id: int,
    expire_ts: int,
) -> None:
    devices = await list_devices(session, user_id)
    for d in devices:
        if d.marzban_username and d.status == 'active':
            try:
                await marz.update_user(d.marzban_username, expire=expire_ts)
            except Exception:
                continue


async def enforce_device_limit(
    *,
    session: AsyncSession,
    marz: MarzbanClient,
    user_id: int,
    limit: int,
) -> list[Device]:
    """If user has > limit active devices -> disable extras (highest slot first)."""
    devices = await list_devices(session, user_id)
    active = [d for d in devices if d.status == 'active']
    if len(active) <= limit:
        return []

    to_disable = sorted(active, key=lambda d: d.slot, reverse=True)[limit:]
    disabled: list[Device] = []
    for d in to_disable:
        disabled.append(await set_device_status(session=session, marz=marz, device=d, status='disabled'))
    return disabled


async def get_device_connection_links(marz: MarzbanClient, marzban_username: str) -> tuple[str | None, str | None]:
    """Return (link, subscription_url)."""
    u = await marz.get_user(marzban_username)
    links = u.get('links') or []
    sub_url = u.get('subscription_url')
    link = links[0] if links else None
    return link, sub_url

async def reissue_device_config(*, session: AsyncSession, marz: MarzbanClient, device: Device) -> None:
    if not device.marzban_username:
        raise ValueError("device_has_no_marzban_username")
    await marz.revoke_subscription(device.marzban_username)
    # ничего больше не нужно: новые ссылки будут валидны при повторном запросе конфига
