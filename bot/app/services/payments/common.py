# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import Any

from ...models import Order


def load_order_meta(order: Order) -> dict[str, Any]:
    """Load order.meta_json as dict (empty when absent)."""
    if not order.meta_json:
        return {}
    try:
        return json.loads(order.meta_json)
    except json.JSONDecodeError:
        return {}


def update_order_meta(order: Order, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into order.meta_json and return updated dict."""
    meta = load_order_meta(order)
    meta.update(updates)
    order.meta_json = json.dumps(meta, ensure_ascii=False)
    return meta