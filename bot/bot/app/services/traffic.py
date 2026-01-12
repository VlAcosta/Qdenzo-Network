# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..marzban.client import MarzbanClient, MarzbanError
from ..models import Device, TrafficSnapshot, User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _extract_usage_bytes(payload: dict) -> tuple[int, int]:
    up = payload.get("up") or payload.get("upload") or payload.get("uplink") or 0
    down = payload.get("down") or payload.get("download") or payload.get("downlink") or 0
    try:
        return int(up), int(down)
    except Exception:
        return 0, 0


async def collect_traffic_snapshots(session: AsyncSession, *, marz: MarzbanClient) -> int:
    devices_q = await session.execute(
        select(Device, User).join(User, User.id == Device.user_id).where(Device.status != "deleted")
    )
    devices = list(devices_q.all())
    if not devices:
        return 0

    totals: dict[int, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0, "tg_id": 0})
    for device, user in devices:
        if not device.marzban_username:
            continue
        try:
            usage = await marz.get_user_usage(device.marzban_username)
        except MarzbanError as exc:
            logger.warning("Traffic collect: Marzban error for %s: %s", device.marzban_username, exc)
            continue
        except Exception as exc:
            logger.warning("Traffic collect: unexpected error for %s: %s", device.marzban_username, exc)
            continue
        up, down = _extract_usage_bytes(usage or {})
        totals[user.id]["up"] += up
        totals[user.id]["down"] += down
        totals[user.id]["tg_id"] = user.tg_id

    now = _now_utc()
    for user_id, agg in totals.items():
        total = agg["up"] + agg["down"]
        snapshot = TrafficSnapshot(
            user_id=user_id,
            tg_id=agg["tg_id"],
            bytes_up=agg["up"],
            bytes_down=agg["down"],
            total_bytes=total,
            collected_at=now,
        )
        session.add(snapshot)

    await session.commit()
    return len(totals)


def _period_start(days: int) -> datetime:
    return _now_utc() - timedelta(days=days)


async def traffic_summary(session: AsyncSession, *, days: int) -> dict[int, int]:
    start = _period_start(days)
    q = await session.execute(
        select(TrafficSnapshot)
        .where(TrafficSnapshot.collected_at >= start)
        .order_by(TrafficSnapshot.user_id, TrafficSnapshot.collected_at.asc())
    )
    snapshots = list(q.scalars().all())
    grouped: dict[int, list[TrafficSnapshot]] = defaultdict(list)
    for snap in snapshots:
        grouped[snap.user_id].append(snap)

    totals: dict[int, int] = {}
    for user_id, items in grouped.items():
        if len(items) < 2:
            totals[user_id] = items[-1].total_bytes if items else 0
            continue
        totals[user_id] = max(items, key=lambda s: s.total_bytes).total_bytes - min(
            items, key=lambda s: s.total_bytes
        ).total_bytes
    return totals


async def top_users_by_traffic(session: AsyncSession, *, days: int, limit: int = 10) -> list[tuple[int, int]]:
    totals = await traffic_summary(session, days=days)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:limit]


async def total_traffic(session: AsyncSession, *, days: int) -> int:
    totals = await traffic_summary(session, days=days)
    return sum(totals.values())