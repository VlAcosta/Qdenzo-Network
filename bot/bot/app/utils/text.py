# -*- coding: utf-8 -*-

from __future__ import annotations

import html
from datetime import datetime, timezone


def h(text: str | None) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html.escape(text or '')


def fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return '—'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Show in ISO but friendly
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def fmt_timedelta_seconds(sec: int) -> str:
    if sec <= 0:
        return '0'
    minutes = sec // 60
    hours = minutes // 60
    days = hours // 24
    rem_h = hours % 24
    rem_m = minutes % 60
    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if rem_h:
        parts.append(f"{rem_h} ч")
    if rem_m and not days:
        parts.append(f"{rem_m} мин")
    return ' '.join(parts) if parts else f"{sec} сек"
