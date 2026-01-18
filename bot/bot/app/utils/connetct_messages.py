# -*- coding: utf-8 -*-

from __future__ import annotations

from .text import h


def build_auto_connect_message(vless_link: str | None) -> str:
    message_text = (
        "Устройство успешно добавлено ✅\n\n"
        "Нажмите кнопку ниже — конфигурация будет\n"
        "импортирована в Happ автоматически."
    )
    if vless_link:
        message_text += f"\n\n<pre><code>{h(vless_link)}</code></pre>"
    return message_text