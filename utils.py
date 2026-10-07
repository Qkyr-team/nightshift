import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from config import ADMIN_IDS
from shared import (  # noqa: F401  (часть имён реэкспортируется для хендлеров)
    CUSTOM_NOTES,
    LINE,
    ORDER_NOTES,
    contact_url,
    esc,
    fmt_dt,
    money,
    order_no,
    split_list,
    status_emoji,
)

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1000

# ---------- кнопки главного меню ----------
BTN_CATALOG = "🛍 Каталог"
BTN_CART = "🛒 Корзина"
BTN_ORDERS = "📦 Мои заказы"
BTN_CUSTOM = "🔎 Заказать под себя"
BTN_SUPPORT = "💬 Поддержка"
BTN_ADMIN = "👑 Админ-панель"
MENU_TEXTS = {BTN_CATALOG, BTN_CART, BTN_ORDERS, BTN_CUSTOM, BTN_SUPPORT, BTN_ADMIN}

# ---------- мелкие помощники ----------

def title(icon, text):
    return f"<b>{icon} {text}</b>\n{LINE}\n\n"


def chunk(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def btn(text, cb=None, url=None):
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=cb)


def mk(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


# ---------- отправка / редактирование сообщений ----------

async def _drop(msg: Message):
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


async def edit_any(msg: Message, text, markup=None):
    """Редактирует текст, а если это фото — подпись (фото остаётся)."""
    try:
        if msg.photo:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


async def send_card(target: Message, text, markup=None, photo=None):
    if photo:
        try:
            if len(text) <= CAPTION_LIMIT:
                return await target.answer_photo(photo, caption=text, reply_markup=markup)
            await target.answer_photo(photo)
        except TelegramBadRequest as e:
            log.warning("Не удалось отправить фото: %s", e)
    return await target.answer(text, reply_markup=markup)


async def show_card(msg: Message, text, markup=None, photo=None):
    """Показывает «карточку» вместо текущего сообщения (с фото или без)."""
    if photo and msg.photo and len(text) <= CAPTION_LIMIT:
        try:
            await msg.edit_media(InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                                 reply_markup=markup)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
    if not photo and not msg.photo:
        await edit_any(msg, text, markup)
        return
    await _drop(msg)
    await send_card(msg, text, markup, photo)


async def say(target, text, markup=None):
    """Callback -> редактируем сообщение, Message -> отправляем новое."""
    if isinstance(target, CallbackQuery):
        await edit_any(target.message, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


async def notify_admins(bot: Bot, text, markup=None, photo=None):
    for admin_id in ADMIN_IDS:
        try:
            if photo and len(text) <= CAPTION_LIMIT:
                await bot.send_photo(admin_id, photo, caption=text, reply_markup=markup)
            else:
                if photo:
                    await bot.send_photo(admin_id, photo)
                await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception as e:  # админ мог не запускать бота
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def tell_user(bot: Bot, user_id, text):
    try:
        await bot.send_message(user_id, text)
        return True
    except Exception as e:
        log.info("Не удалось написать пользователю %s: %s", user_id, e)
        return False


# ---------- карточки заказов ----------

def order_text(o, items, admin=False):
    t = f"<b>🛒 ЗАКАЗ {order_no(o['id'])}</b>  {status_emoji(o['status'])} {esc(o['status'])}\n{LINE}\n\n"
    if admin:
        un = f" (@{esc(o['username'])})" if o["username"] else ""
        t += f"👤 {esc(o['first_name'] or '—')}{un}\n🆔 <code>{o['user_id']}</code>\n"
    t += f"📱 <b>Контакт:</b> {esc(o['contact'])}\n"
    if o["comment"]:
        t += f"💬 {esc(o['comment'])}\n"
    t += "\n"
    for i in items:
        t += (f"• <b>{esc(i['name'])}</b>\n"
              f"   {esc(i['size'])} · {esc(i['color'])} · ×{i['qty']} — {money(i['price'] * i['qty'])}\n")
    t += f"\n<b>Итого: {money(o['total'])}</b>\n🕒 {fmt_dt(o['created_at'])}"
    return t


def order_admin_kb(o, back=False):
    rows = [
        [btn("💬 Написать клиенту", url=contact_url(o["user_id"], o["username"]))],
        [btn("🔄 Статус", f"aos:{o['id']}"), btn("✉️ Через бота", f"reply:{o['user_id']}")],
    ]
    if back:
        rows.append([btn("← Заказы", "ao_list:all:0")])
    return mk(*rows)


def custom_text(r, admin=False):
    t = f"<b>🔎 ЗАЯВКА {order_no(r['id'])}</b>  {status_emoji(r['status'], True)} {esc(r['status'])}\n{LINE}\n\n"
    if admin:
        un = f" (@{esc(r['username'])})" if r["username"] else ""
        t += f"👤 {esc(r['first_name'] or '—')}{un}\n🆔 <code>{r['user_id']}</code>\n"
    t += (f"📝 {esc(r['description'])}\n\n"
          f"💶 <b>Бюджет:</b> {esc(r['budget'] or '—')}\n"
          f"📱 <b>Контакт:</b> {esc(r['contact'] or '—')}\n"
          f"🕒 {fmt_dt(r['created_at'])}")
    return t


def custom_admin_kb(r, back=False):
    rows = [
        [btn("💬 Написать клиенту", url=contact_url(r["user_id"], r["username"]))],
        [btn("🔄 Статус", f"acs:{r['id']}"), btn("✉️ Через бота", f"reply:{r['user_id']}")],
    ]
    if back:
        rows.append([btn("← Заявки", "ac_list:0")])
    return mk(*rows)
