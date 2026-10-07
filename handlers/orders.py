from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
from config import ADMIN_IDS
from utils import (
    BTN_CUSTOM,
    BTN_ORDERS,
    BTN_SUPPORT,
    LINE,
    btn,
    contact_url,
    custom_admin_kb,
    custom_text,
    edit_any,
    esc,
    mk,
    money,
    notify_admins,
    order_no,
    order_text,
    say,
    show_card,
    status_emoji,
    title,
)

router = Router()


class CustomState(StatesGroup):
    description = State()
    budget = State()
    contact = State()


class SupportState(StatesGroup):
    message = State()


CANCEL = btn("❌ Отмена", "cancel_state")


# =========================
# 📦 МОИ ЗАКАЗЫ
# =========================

def my_orders_view(user_id):
    orders = db.get_user_orders(user_id)
    if not orders:
        return (title("📦", "МОИ ЗАКАЗЫ") + "У тебя пока нет заказов.",
                mk([btn("🛍 В каталог", "catalog")]))
    rows = [
        [btn(f"{status_emoji(o['status'])} {order_no(o['id'])} · {money(o['total'])} · {o['status']}",
             f"mo:{o['id']}")]
        for o in orders
    ]
    rows.append([btn("← Главное меню", "back_to_menu")])
    return title("📦", "МОИ ЗАКАЗЫ") + "Нажми на заказ, чтобы посмотреть детали:", mk(*rows)


@router.message(F.text == BTN_ORDERS)
async def my_orders_message(message: Message):
    text, markup = my_orders_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "my_orders")
async def my_orders_callback(callback: CallbackQuery):
    text, markup = my_orders_view(callback.from_user.id)
    await show_card(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("mo:"))
async def my_order_detail(callback: CallbackQuery):
    order = db.get_order(int(callback.data.split(":")[1]))
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    text = order_text(order, db.get_order_items(order["id"]))
    await edit_any(callback.message, text, mk([btn("← Мои заказы", "my_orders")]))
    await callback.answer()


# =========================
# 🔎 ЗАКАЗ ПОД СЕБЯ
# =========================

@router.message(F.text == BTN_CUSTOM)
async def custom_start(message: Message, state: FSMContext):
    await state.set_state(CustomState.description)
    await message.answer(
        title("🔎", "ЗАКАЗ ПОД СЕБЯ") + "Опиши вещь, которую хочешь найти.\n\n"
        "Например:\n<i>Чёрное oversized-худи Nike, размер M</i>\n\n"
        "📸 Можно приложить фото — просто отправь его с подписью.",
        reply_markup=mk([CANCEL]),
    )


@router.message(CustomState.description, F.text | F.photo)
async def custom_description(message: Message, state: FSMContext):
    desc = (message.text or message.caption or "").strip()
    photo_id = message.photo[-1].file_id if message.photo else None
    if len(desc) > 900:
        await message.answer("⚠️ Слишком длинно, сократи описание до 900 символов.")
        return
    await state.update_data(description=desc or "(фото без описания)", photo_id=photo_id)
    await state.set_state(CustomState.budget)
    await message.answer(
        title("💶", "БЮДЖЕТ") + "Напиши максимальную сумму.\n\n"
        "Например: <i>80 €</i>\nИли: <i>без ограничений</i>",
        reply_markup=mk([CANCEL]),
    )


@router.message(CustomState.description)
async def custom_description_bad(message: Message):
    await message.answer("⚠️ Отправь описание текстом или фото с подписью.")


@router.message(CustomState.budget, F.text)
async def custom_budget(message: Message, state: FSMContext):
    await state.update_data(budget=message.text.strip()[:100])
    await state.set_state(CustomState.contact)
    u = message.from_user
    rows = []
    if u.username:
        rows.append([btn("✅ Использовать мой @username", "cu_user")])
    rows.append([CANCEL])
    await message.answer(
        title("📱", "КОНТАКТ") + "Как с тобой связаться?\n\n"
        "<i>Нажми кнопку или напиши телефон / другой @username.</i>",
        reply_markup=mk(*rows),
    )


@router.message(CustomState.budget)
async def custom_budget_bad(message: Message):
    await message.answer("⚠️ Напиши бюджет текстом.")


async def _finish_custom(target, state: FSMContext, bot: Bot, user, contact: str):
    data = await state.get_data()
    rid = db.create_custom_order(user.id, user.username, user.full_name, data["description"],
                                 data.get("photo_id"), data.get("budget"), contact)
    await state.clear()
    r = db.get_custom_order(rid)
    await say(
        target,
        f"<b>✅ ЗАЯВКА ПРИНЯТА</b>\n{LINE}\n\n"
        f"<b>Номер:</b> {order_no(rid)}\n"
        f"<b>Бюджет:</b> {esc(r['budget'])}\n\n"
        "Мы посмотрим варианты и свяжемся с тобой 🖤",
    )
    await notify_admins(bot, "🔔 <b>НОВАЯ ЗАЯВКА ПОД ЗАКАЗ</b>\n\n" + custom_text(r, admin=True),
                        custom_admin_kb(r), photo=r["photo_id"])


@router.callback_query(CustomState.contact, F.data == "cu_user")
async def custom_use_username(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await _finish_custom(callback, state, bot, callback.from_user, f"@{callback.from_user.username}")
    await callback.answer("Заявка принята ✅")


@router.message(CustomState.contact, F.text)
async def custom_contact(message: Message, state: FSMContext, bot: Bot):
    await _finish_custom(message, state, bot, message.from_user, message.text.strip()[:100])


@router.message(CustomState.contact)
async def custom_contact_bad(message: Message):
    await message.answer("⚠️ Отправь контакт текстом.")


# =========================
# 💬 ПОДДЕРЖКА
# =========================

@router.message(F.text == BTN_SUPPORT)
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportState.message)
    await message.answer(
        title("💬", "ПОДДЕРЖКА") + "Напиши свой вопрос — мы ответим прямо здесь.\n"
        "Можно приложить фото.",
        reply_markup=mk([CANCEL]),
    )


async def forward_support(message: Message, bot: Bot):
    """Сохраняет сообщение клиента в базу (видно в веб-панели) и уведомляет админов в Telegram."""
    u = message.from_user
    db.upsert_user(u.id, u.username, u.full_name)
    text = (message.text or message.caption or "").strip()
    photo_id = message.photo[-1].file_id if message.photo else None
    db.add_message(u.id, "in", text, photo_id)

    un = f" (@{esc(u.username)})" if u.username else ""
    body = esc(text) or "<i>(вложение ниже)</i>"
    header = (f"<b>💬 ОБРАЩЕНИЕ</b>\n{LINE}\n\n👤 {esc(u.full_name)}{un}\n"
              f"🆔 <code>{u.id}</code>\n\n{body}")
    markup = mk(
        [btn("💬 Открыть чат", url=contact_url(u.id, u.username))],
        [btn("✉️ Ответить через бота", f"reply:{u.id}")],
    )
    await notify_admins(bot, header, markup)
    if not message.text:  # фото/файл — пересылаем копией
        for admin_id in ADMIN_IDS:
            try:
                await message.copy_to(admin_id)
            except Exception:
                pass


@router.message(SupportState.message)
async def support_message(message: Message, state: FSMContext, bot: Bot):
    await forward_support(message, bot)
    await state.clear()
    await message.answer("✅ Сообщение отправлено. Мы ответим тебе здесь, в боте.")
