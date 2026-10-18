"""Отправка уведомления о заявке в Telegram (если заданы BOT_TOKEN и CHAT_ID)."""
import logging
import os

import httpx

log = logging.getLogger("nuance.telegram")


def notify(name: str, phone: str, service: str) -> None:
    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    if not token or not chat_id:
        return  # Telegram не настроен, заявка всё равно сохранена в базе
    text = f"Новая заявка\nИмя: {name}\nТелефон: {phone}\nУслуга: {service}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        # Логируем только тип ошибки: в тексте исключения может быть токен.
        log.warning("Не удалось отправить в Telegram: %s", type(exc).__name__)
