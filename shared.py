"""Чистые помощники без зависимости от aiogram — используются и ботом, и веб-панелью."""
from datetime import datetime, timezone
from html import escape as _escape
from zoneinfo import ZoneInfo

from config import CURRENCY, TIMEZONE
from database import CUSTOM_STATUSES, ORDER_STATUSES

LINE = "━━━━━━━━━━━━━━━━━"

# Что писать клиенту при смене статуса
ORDER_NOTES = {
    "Подтверждён": "Заказ подтверждён ✅ Мы уже занимаемся им.",
    "У поставщика": "Заказ передан поставщику. Скоро будут новости.",
    "В пути": "Твой заказ в пути 🚚",
    "Получен": "Заказ получен. Спасибо, что выбрал NIGHTSHIFT 🖤",
    "Отменён": "Заказ отменён. Если это ошибка — просто напиши сюда.",
}
CUSTOM_NOTES = {
    "В поиске": "Мы ищем твою вещь 🔎",
    "Найдено": "Мы нашли подходящий вариант! Скоро напишем тебе детали.",
    "Закрыта": "Заявка закрыта. Если нужна другая вещь — оформи новую заявку.",
}


def esc(v):
    return _escape("" if v is None else str(v))


def money(v):
    return f"{CURRENCY}{float(v):.2f}"


def order_no(i):
    return f"#{int(i):04d}"


def split_list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def status_emoji(status, custom=False):
    for name, emoji in (CUSTOM_STATUSES if custom else ORDER_STATUSES):
        if name == status:
            return emoji
    return "▫️"


def fmt_dt(s):
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(s or "")


def contact_url(user_id, username):
    if username:
        return f"https://t.me/{username.lstrip('@')}"
    return f"tg://user?id={user_id}"


def client_message(shop_name, text):
    """Единый вид сообщения от магазина клиенту (бот и панель)."""
    return f"<b>💬 {esc(shop_name)}</b>\n{LINE}\n\n{esc(text)}"
