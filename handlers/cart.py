from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
from utils import (
    BTN_CART,
    LINE,
    btn,
    edit_any,
    esc,
    mk,
    money,
    notify_admins,
    order_admin_kb,
    order_no,
    order_text,
    say,
    show_card,
    title,
)

router = Router()


class Checkout(StatesGroup):
    contact = State()
    comment = State()
    confirm = State()


# ---------- корзина ----------

def render_cart(user_id):
    items = db.get_cart(user_id)
    if not items:
        return (title("🛒", "КОРЗИНА") + "Пока пусто.\nДобавь что-нибудь из каталога 🖤",
                mk([btn("🛍 В каталог", "catalog")]))
    lines, rows, total = [], [], 0
    for n, i in enumerate(items, 1):
        sub = i["price"] * i["qty"]
        total += sub
        lines.append(f"<b>{n}. {esc(i['name'])}</b>\n    {esc(i['size'])} · {esc(i['color'])} · ×{i['qty']} — {money(sub)}")
        rows.append([
            btn("➖", f"cq:{i['id']}:-1"),
            btn(f"{n} · ×{i['qty']}", "noop"),
            btn("➕", f"cq:{i['id']}:1"),
            btn("🗑", f"cd:{i['id']}"),
        ])
    rows.append([btn("🧹 Очистить", "cclear"), btn("✅ Оформить заказ", "checkout")])
    rows.append([btn("🛍 Продолжить покупки", "catalog")])
    text = title("🛒", "КОРЗИНА") + "\n\n".join(lines) + f"\n\n{LINE}\n<b>Итого: {money(total)}</b>"
    return text, mk(*rows)


@router.message(F.text == BTN_CART)
async def cart_message(message: Message):
    text, markup = render_cart(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    text, markup = render_cart(callback.from_user.id)
    await show_card(callback.message, text, markup)
    await callback.answer()


async def _refresh(callback: CallbackQuery):
    text, markup = render_cart(callback.from_user.id)
    await edit_any(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cq:"))
async def cart_qty(callback: CallbackQuery):
    _, cid, delta = callback.data.split(":")
    db.change_qty(int(cid), callback.from_user.id, int(delta))
    await _refresh(callback)


@router.callback_query(F.data.startswith("cd:"))
async def cart_delete(callback: CallbackQuery):
    db.remove_cart_item(int(callback.data.split(":")[1]), callback.from_user.id)
    await _refresh(callback)


@router.callback_query(F.data == "cclear")
async def cart_clear(callback: CallbackQuery):
    db.clear_cart(callback.from_user.id)
    await _refresh(callback)


# ---------- оформление заказа ----------

def _contact_kb(username):
    rows = []
    if username:
        rows.append([btn("✅ Использовать мой @username", "co_user")])
    rows.append([btn("❌ Отмена", "co_cancel")])
    return mk(*rows)


@router.callback_query(F.data == "checkout")
async def checkout_start(callback: CallbackQuery, state: FSMContext):
    if not db.get_cart(callback.from_user.id):
        await callback.answer("Корзина пуста.", show_alert=True)
        return
    await state.set_state(Checkout.contact)
    u = callback.from_user
    hint = ("Нажми кнопку ниже или напиши другой контакт (телефон, другой @username)."
            if u.username else
            "У тебя не указан @username — напиши номер телефона или другой способ связи.")
    await edit_any(
        callback.message,
        title("📱", "КОНТАКТ") + f"Как нам с тобой связаться?\n\n<i>{hint}</i>",
        _contact_kb(u.username),
    )
    await callback.answer()


async def _ask_comment(target, state: FSMContext):
    await state.set_state(Checkout.comment)
    await say(
        target,
        title("💬", "КОММЕНТАРИЙ")
        + "Город, пожелания, удобное время для связи — всё, что считаешь важным.\n\n"
          "<i>Можно пропустить.</i>",
        mk([btn("⏭ Пропустить", "co_skip")], [btn("❌ Отмена", "co_cancel")]),
    )


@router.callback_query(Checkout.contact, F.data == "co_user")
async def checkout_use_username(callback: CallbackQuery, state: FSMContext):
    await state.update_data(contact=f"@{callback.from_user.username}")
    await _ask_comment(callback, state)
    await callback.answer()


@router.message(Checkout.contact)
async def checkout_contact(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("⚠️ Отправь контакт текстом (до 100 символов).")
        return
    await state.update_data(contact=text)
    await _ask_comment(message, state)


async def _show_summary(target, state: FSMContext, user_id):
    data = await state.get_data()
    items = db.get_cart(user_id)
    if not items:
        await state.clear()
        await say(target, "Корзина пуста.", None)
        return
    total = sum(i["price"] * i["qty"] for i in items)
    lines = "\n".join(
        f"• {esc(i['name'])} — {esc(i['size'])} · {esc(i['color'])} · ×{i['qty']}" for i in items
    )
    text = (title("🧾", "ПРОВЕРЬ ЗАКАЗ") + f"{lines}\n\n"
            f"📱 <b>Контакт:</b> {esc(data['contact'])}\n"
            + (f"💬 {esc(data['comment'])}\n" if data.get("comment") else "")
            + f"\n<b>Итого: {money(total)}</b>")
    await state.set_state(Checkout.confirm)
    await say(target, text, mk([btn("✅ Подтвердить заказ", "co_confirm")], [btn("❌ Отмена", "co_cancel")]))


@router.callback_query(Checkout.comment, F.data == "co_skip")
async def checkout_skip_comment(callback: CallbackQuery, state: FSMContext):
    await state.update_data(comment=None)
    await _show_summary(callback, state, callback.from_user.id)
    await callback.answer()


@router.message(Checkout.comment)
async def checkout_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or len(text) > 500:
        await message.answer("⚠️ Напиши комментарий текстом (до 500 символов) или нажми «Пропустить».")
        return
    await state.update_data(comment=text)
    await _show_summary(message, state, message.from_user.id)


@router.callback_query(Checkout.confirm, F.data == "co_confirm")
async def checkout_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    u = callback.from_user
    oid = db.create_order_from_cart(u.id, u.username, u.full_name, data["contact"], data.get("comment"))
    await state.clear()
    if not oid:
        await callback.answer("Корзина пуста.", show_alert=True)
        return

    order = db.get_order(oid)
    items = db.get_order_items(oid)
    await edit_any(
        callback.message,
        f"<b>✅ ЗАКАЗ ПРИНЯТ</b>\n{LINE}\n\n"
        f"<b>Номер:</b> {order_no(oid)}\n"
        f"<b>Сумма:</b> {money(order['total'])}\n\n{LINE}\n"
        "Мы свяжемся с тобой, чтобы подтвердить заказ 🖤",
        mk([btn("📦 Мои заказы", "my_orders")]),
    )
    await notify_admins(bot, "🔔 <b>НОВЫЙ ЗАКАЗ</b>\n\n" + order_text(order, items, admin=True),
                        order_admin_kb(order))
    await callback.answer("Заказ принят ✅")


@router.callback_query(F.data == "co_cancel")
async def checkout_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = render_cart(callback.from_user.id)
    await edit_any(callback.message, text, markup)
    await callback.answer("Отменено")
