import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
from config import ADMIN_IDS, SHOP_NAME
from shared import client_message
from database import CUSTOM_STATUSES, ORDER_STATUSES
from utils import (
    BTN_ADMIN,
    CUSTOM_NOTES,
    LINE,
    ORDER_NOTES,
    btn,
    chunk,
    custom_admin_kb,
    custom_text,
    edit_any,
    esc,
    mk,
    money,
    order_admin_kb,
    order_no,
    order_text,
    say,
    send_card,
    show_card,
    split_list,
    status_emoji,
    tell_user,
    title,
)

router = Router()
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

PER_PAGE = 6
CANCEL_KB = mk([btn("❌ Отмена", "adm_cancel")])


class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    category = State()
    sizes = State()
    colors = State()
    photo = State()


class EditProduct(StatesGroup):
    value = State()


class Reply(StatesGroup):
    text = State()


class Broadcast(StatesGroup):
    content = State()
    confirm = State()


async def need_text(message: Message, hint="Отправь текстом."):
    t = (message.text or "").strip()
    if not t:
        await message.answer(f"⚠️ {hint}")
        return None
    return t


# =========================
# 👑 ГЛАВНОЕ МЕНЮ АДМИНА
# =========================

def admin_menu_view():
    s = db.stats()
    hidden = f" (скрыто {s['hidden']})" if s["hidden"] else ""
    text = (
        title("👑", f"{esc(SHOP_NAME)} · ADMIN")
        + f"🛒 Новых заказов: <b>{s['new_orders']}</b>\n"
        f"🔎 Новых заявок: <b>{s['new_custom']}</b>\n"
        f"📦 Товаров: <b>{s['products']}</b>{hidden}\n"
        f"👥 Клиентов: <b>{s['users']}</b>\n\n"
        f"💰 Сумма заказов: <b>{money(s['revenue'])}</b>\n"
        f"<i>всего заказов: {s['orders']}, без отменённых</i>"
    )
    markup = mk(
        [btn(f"🛒 Заказы ({s['new_orders']})", "ao_list:new:0"),
         btn(f"🔎 Заявки ({s['new_custom']})", "ac_list:0")],
        [btn("📦 Товары", "ap"), btn("➕ Добавить товар", "addp")],
        [btn("📣 Рассылка", "abc")],
        [btn("← Главное меню", "back_to_menu")],
    )
    return text, markup


@router.message(F.text == BTN_ADMIN)
@router.message(Command("admin"))
async def admin_menu_message(message: Message, state: FSMContext):
    await state.clear()
    text, markup = admin_menu_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.in_({"adm", "adm_cancel"}))
async def admin_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = admin_menu_view()
    await show_card(callback.message, text, markup)
    await callback.answer()


# =========================
# 🛒 ЗАКАЗЫ
# =========================

FILTER_TABS = [("new", "🟡 Новые"), ("work", "🔵 Работа"), ("done", "⚪️ Архив"), ("all", "Все")]
FILTER_LABELS = {"new": "Новые", "work": "В работе", "done": "Закрытые", "all": "Все"}


@router.callback_query(F.data.startswith("ao_list:"))
async def orders_list(callback: CallbackQuery):
    _, flt, page = callback.data.split(":")
    total = db.count_orders(flt)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(max(int(page), 0), pages - 1)
    orders = db.list_orders(flt, PER_PAGE, page * PER_PAGE)

    rows = []
    for o in orders:
        who = (o["first_name"] or o["username"] or "—")[:14]
        rows.append([btn(f"{status_emoji(o['status'])} {order_no(o['id'])} · {money(o['total'])} · {who}",
                         f"ao:{o['id']}")])
    rows.append([btn(("• " if key == flt else "") + label, f"ao_list:{key}:0") for key, label in FILTER_TABS])
    if pages > 1:
        rows.append([
            btn("◀", f"ao_list:{flt}:{page - 1}"),
            btn(f"{page + 1} / {pages}", "noop"),
            btn("▶", f"ao_list:{flt}:{page + 1}"),
        ])
    rows.append([btn("← Админ-панель", "adm")])

    text = title("🛒", "ЗАКАЗЫ") + f"Фильтр: <b>{FILTER_LABELS[flt]}</b> · найдено: {total}"
    if not orders:
        text += "\n\nЗдесь пока пусто."
    await show_card(callback.message, text, mk(*rows))
    await callback.answer()


@router.callback_query(F.data.startswith("ao:"))
async def order_card(callback: CallbackQuery):
    o = db.get_order(int(callback.data.split(":")[1]))
    if not o:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    text = order_text(o, db.get_order_items(o["id"]), admin=True)
    await show_card(callback.message, text, order_admin_kb(o, back=True))
    await callback.answer()


def _status_kb(prefix_pick, back_cb, statuses, current, item_id):
    buttons = [
        btn(("✓ " if name == current else "") + f"{emoji} {name}", f"{prefix_pick}:{item_id}:{i}")
        for i, (name, emoji) in enumerate(statuses)
    ]
    return mk(*chunk(buttons, 2), [btn("← Назад", back_cb)])


@router.callback_query(F.data.startswith("aos:"))
async def order_status_menu(callback: CallbackQuery):
    oid = int(callback.data.split(":")[1])
    o = db.get_order(oid)
    if not o:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    await show_card(
        callback.message,
        title("🔄", f"СТАТУС {order_no(oid)}") + "Клиент получит уведомление о новом статусе.",
        _status_kb("aoset", f"ao:{oid}", ORDER_STATUSES, o["status"], oid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aoset:"))
async def order_set_status(callback: CallbackQuery, bot: Bot):
    _, oid, idx = callback.data.split(":")
    oid = int(oid)
    status = ORDER_STATUSES[int(idx)][0]
    o = db.get_order(oid)
    if not o:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if o["status"] != status:
        db.update_order_status(oid, status)
        note = ORDER_NOTES.get(status)
        if note:
            await tell_user(bot, o["user_id"],
                            f"<b>📦 Заказ {order_no(oid)}</b>\n{status_emoji(status)} <b>{esc(status)}</b>\n\n{note}")
    o = db.get_order(oid)
    await show_card(callback.message, order_text(o, db.get_order_items(oid), admin=True),
                    order_admin_kb(o, back=True))
    await callback.answer(f"Статус: {status}")


# =========================
# 🔎 ЗАЯВКИ ПОД ЗАКАЗ
# =========================

@router.callback_query(F.data.startswith("ac_list:"))
async def custom_list(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    total = db.count_custom_orders()
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(max(page, 0), pages - 1)
    items = db.list_custom_orders(PER_PAGE, page * PER_PAGE)

    rows = []
    for r in items:
        short = (r["description"] or "—").replace("\n", " ")[:22]
        rows.append([btn(f"{status_emoji(r['status'], True)} {order_no(r['id'])} · {short}", f"ac:{r['id']}")])
    if pages > 1:
        rows.append([
            btn("◀", f"ac_list:{page - 1}"),
            btn(f"{page + 1} / {pages}", "noop"),
            btn("▶", f"ac_list:{page + 1}"),
        ])
    rows.append([btn("← Админ-панель", "adm")])
    text = title("🔎", "ЗАЯВКИ ПОД ЗАКАЗ") + f"Всего заявок: {total}"
    if not items:
        text += "\n\nЗаявок пока нет."
    await show_card(callback.message, text, mk(*rows))
    await callback.answer()


@router.callback_query(F.data.startswith("ac:"))
async def custom_card(callback: CallbackQuery):
    r = db.get_custom_order(int(callback.data.split(":")[1]))
    if not r:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await show_card(callback.message, custom_text(r, admin=True), custom_admin_kb(r, back=True), r["photo_id"])
    await callback.answer()


@router.callback_query(F.data.startswith("acs:"))
async def custom_status_menu(callback: CallbackQuery):
    rid = int(callback.data.split(":")[1])
    r = db.get_custom_order(rid)
    if not r:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await show_card(
        callback.message,
        title("🔄", f"СТАТУС ЗАЯВКИ {order_no(rid)}") + "Клиент получит уведомление.",
        _status_kb("acset", f"ac:{rid}", CUSTOM_STATUSES, r["status"], rid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acset:"))
async def custom_set_status(callback: CallbackQuery, bot: Bot):
    _, rid, idx = callback.data.split(":")
    rid = int(rid)
    status = CUSTOM_STATUSES[int(idx)][0]
    r = db.get_custom_order(rid)
    if not r:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if r["status"] != status:
        db.update_custom_status(rid, status)
        note = CUSTOM_NOTES.get(status)
        if note:
            await tell_user(bot, r["user_id"],
                            f"<b>🔎 Заявка {order_no(rid)}</b>\n{status_emoji(status, True)} <b>{esc(status)}</b>\n\n{note}")
    r = db.get_custom_order(rid)
    await show_card(callback.message, custom_text(r, admin=True), custom_admin_kb(r, back=True), r["photo_id"])
    await callback.answer(f"Статус: {status}")


# =========================
# ✉️ ОТВЕТ КЛИЕНТУ ЧЕРЕЗ БОТА
# =========================

@router.callback_query(F.data.startswith("reply:"))
async def reply_start(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split(":")[1])
    await state.set_state(Reply.text)
    await state.update_data(uid=uid)
    await callback.message.answer(
        f"✉️ Напиши сообщение клиенту <code>{uid}</code> (текст или фото).",
        reply_markup=CANCEL_KB,
    )
    await callback.answer()


@router.message(Reply.text)
async def reply_send(message: Message, state: FSMContext, bot: Bot):
    uid = (await state.get_data())["uid"]
    try:
        if message.text:
            await bot.send_message(uid, client_message(SHOP_NAME, message.text))
        else:
            await bot.send_message(uid, f"<b>💬 {esc(SHOP_NAME)}</b>")
            await message.copy_to(uid)
        photo_id = message.photo[-1].file_id if message.photo else None
        db.add_message(uid, "out", message.text or message.caption or "", photo_id)
        db.mark_thread_read(uid)
        await message.answer("✅ Отправлено клиенту.")
    except Exception:
        await message.answer("❌ Не удалось доставить (клиент мог заблокировать бота).")
    await state.clear()


# =========================
# 📦 ТОВАРЫ
# =========================

FIELD_LABELS = {
    "name": "название", "description": "описание", "price": "цену",
    "category": "категорию", "sizes": "размеры", "colors": "цвета", "photo": "фото",
}


def products_categories_view():
    cats = db.get_categories_admin()
    rows = [[btn(f"📦 {c['name']} · {c['cnt']}", f"apc:{c['id']}")] for c in cats]
    rows.append([btn("➕ Добавить товар", "addp")])
    rows.append([btn("← Админ-панель", "adm")])
    text = title("📦", "ТОВАРЫ") + ("Выбери категорию:" if cats else "Товаров пока нет.")
    return text, mk(*rows)


def product_card_view(pid):
    p = db.get_product(pid)
    if not p:
        return None
    sizes = " · ".join(split_list(p["sizes"])) or "—"
    colors = " · ".join(split_list(p["colors"])) or "—"
    state = "🟢 виден в каталоге" if p["active"] else "⚪️ скрыт"
    text = (
        f"<b>📦 {esc(p['name'])}</b>\n{LINE}\n\n{esc(p['description'])}\n\n"
        f"💶 <b>{money(p['price'])}</b>\n🗂 {esc(p['category'])}\n"
        f"📏 {esc(sizes)}\n🎨 {esc(colors)}\n\n{state} · ID {p['id']}"
    )
    markup = mk(
        [btn("✏️ Название", f"ape:{pid}:name"), btn("📝 Описание", f"ape:{pid}:description")],
        [btn("💶 Цена", f"ape:{pid}:price"), btn("🗂 Категория", f"ape:{pid}:category")],
        [btn("📏 Размеры", f"ape:{pid}:sizes"), btn("🎨 Цвета", f"ape:{pid}:colors")],
        [btn("🖼 Фото", f"ape:{pid}:photo"),
         btn("🙈 Скрыть" if p["active"] else "👁 Показать", f"apt:{pid}")],
        [btn("🗑 Удалить", f"apd:{pid}")],
        [btn("← К списку", f"apc:{p['category_id']}")],
    )
    return text, markup, p["photo_id"]


@router.callback_query(F.data == "ap")
async def products_categories(callback: CallbackQuery):
    text, markup = products_categories_view()
    await show_card(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("apc:"))
async def products_in_category(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    cat = db.get_category(cat_id)
    if not cat:
        await products_categories(callback)
        return
    rows = [
        [btn(f"{'🟢' if p['active'] else '⚪️'} {p['name'][:28]} · {money(p['price'])}", f"apr:{p['id']}")]
        for p in db.get_products(cat_id, only_active=False)
    ]
    rows.append([btn("← Товары", "ap")])
    await show_card(callback.message, title("📦", esc(cat["name"]).upper()) + "Выбери товар для редактирования:",
                    mk(*rows))
    await callback.answer()


@router.callback_query(F.data.startswith("apr:"))
async def product_open(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    view = product_card_view(int(callback.data.split(":")[1]))
    if not view:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await show_card(callback.message, *view)
    await callback.answer()


@router.callback_query(F.data.startswith("apt:"))
async def product_toggle(callback: CallbackQuery):
    pid = int(callback.data.split(":")[1])
    db.toggle_product(pid)
    view = product_card_view(pid)
    if view:
        await show_card(callback.message, *view)
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("apd:"))
async def product_delete_ask(callback: CallbackQuery):
    pid = int(callback.data.split(":")[1])
    p = db.get_product(pid)
    if not p:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await edit_any(
        callback.message,
        f"<b>🗑 Удалить «{esc(p['name'])}»?</b>\n\nЭто нельзя отменить. "
        "Если товар нужно просто убрать из каталога — лучше нажми «Скрыть».",
        mk([btn("🗑 Да, удалить", f"apdy:{pid}")], [btn("← Нет, назад", f"apr:{pid}")]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("apdy:"))
async def product_delete(callback: CallbackQuery):
    db.delete_product(int(callback.data.split(":")[1]))
    text, markup = products_categories_view()
    await show_card(callback.message, text, markup)
    await callback.answer("Товар удалён", show_alert=True)


# ---------- редактирование поля ----------

@router.callback_query(F.data.startswith("ape:"))
async def product_edit_start(callback: CallbackQuery, state: FSMContext):
    _, pid, field = callback.data.split(":")
    p = db.get_product(int(pid))
    if not p or field not in FIELD_LABELS:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await state.set_state(EditProduct.value)
    await state.update_data(pid=int(pid), field=field)
    hint = ""
    if field in ("sizes", "colors"):
        hint = "\nЧерез запятую. Чтобы очистить — отправь «-»."
    elif field == "price":
        hint = "\nНапример: <code>59.90</code>"
    current = {"category": p["category"], "photo": None}.get(field, p[field] if field != "price" else money(p["price"]))
    cur = f"\n\nСейчас: <code>{esc(current)}</code>" if current else ""
    prompt = (f"✏️ Отправь {'новое фото' if field == 'photo' else 'новое значение'} "
              f"— <b>{FIELD_LABELS[field]}</b>.{hint}{cur}")
    await callback.message.answer(prompt, reply_markup=mk([btn("❌ Отмена", f"apr:{pid}")]))
    await callback.answer()


@router.message(EditProduct.value)
async def product_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    pid, field = data["pid"], data["field"]

    if field == "photo":
        if not message.photo:
            await message.answer("⚠️ Отправь именно фотографию.")
            return
        db.update_product(pid, photo_id=message.photo[-1].file_id)
    else:
        val = await need_text(message)
        if val is None:
            return
        if field == "price":
            try:
                price = float(val.replace(",", ".").replace("€", "").strip())
                if price <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("❌ Введи цену числом, например 59.90")
                return
            db.update_product(pid, price=price)
        elif field == "category":
            db.set_product_category(pid, val)
            db.cleanup_categories()
        elif field in ("sizes", "colors"):
            db.update_product(pid, **{field: "" if val in {"-", "—"} else val})
        else:
            db.update_product(pid, **{field: val})

    await state.clear()
    await message.answer("✅ Сохранено.")
    view = product_card_view(pid)
    if view:
        await send_card(message, *view)


# ---------- добавление товара ----------

def step(n, text):
    return f"<b>➕ НОВЫЙ ТОВАР</b> · шаг {n}/7\n{LINE}\n\n{text}"


@router.callback_query(F.data == "addp")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddProduct.name)
    await show_card(callback.message, step(1, "Введи <b>название</b> товара:"), CANCEL_KB)
    await callback.answer()


@router.message(AddProduct.name)
async def add_name(message: Message, state: FSMContext):
    t = await need_text(message, "Название — текстом.")
    if t is None:
        return
    await state.update_data(name=t)
    await state.set_state(AddProduct.description)
    await message.answer(step(2, "Введи <b>описание</b> товара:"), reply_markup=CANCEL_KB)


@router.message(AddProduct.description)
async def add_description(message: Message, state: FSMContext):
    t = await need_text(message, "Описание — текстом.")
    if t is None:
        return
    await state.update_data(description=t)
    await state.set_state(AddProduct.price)
    await message.answer(step(3, "Введи <b>цену</b>.\n\nНапример: <code>59.90</code>"), reply_markup=CANCEL_KB)


@router.message(AddProduct.price)
async def add_price(message: Message, state: FSMContext):
    t = await need_text(message, "Введи цену числом.")
    if t is None:
        return
    try:
        price = float(t.replace(",", ".").replace("€", "").strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи цену числом, например 59.90")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.category)
    cats = db.get_categories_admin()
    rows = chunk([btn(c["name"], f"addcat:{c['id']}") for c in cats], 2)
    rows.append([btn("❌ Отмена", "adm_cancel")])
    await message.answer(
        step(4, "Выбери <b>категорию</b> кнопкой или напиши новую (например: <i>Худи</i>):"),
        reply_markup=mk(*rows),
    )


async def _ask_sizes(target, state: FSMContext, category_name):
    await state.update_data(category=category_name)
    await state.set_state(AddProduct.sizes)
    await say(
        target,
        step(5, f"Категория: <b>{esc(category_name)}</b>\n\nВведи <b>размеры</b> через запятую.\n\n"
                "Например: <code>S,M,L,XL</code>\nЕсли размеров нет — отправь «-»."),
        CANCEL_KB,
    )


@router.callback_query(AddProduct.category, F.data.startswith("addcat:"))
async def add_category_pick(callback: CallbackQuery, state: FSMContext):
    cat = db.get_category(int(callback.data.split(":")[1]))
    if not cat:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    await _ask_sizes(callback, state, cat["name"])
    await callback.answer()


@router.message(AddProduct.category)
async def add_category_text(message: Message, state: FSMContext):
    t = await need_text(message, "Название категории — текстом.")
    if t is None:
        return
    await _ask_sizes(message, state, t[:40])


@router.message(AddProduct.sizes)
async def add_sizes(message: Message, state: FSMContext):
    t = await need_text(message, "Размеры — текстом.")
    if t is None:
        return
    await state.update_data(sizes="" if t in {"-", "—"} else t)
    await state.set_state(AddProduct.colors)
    await message.answer(
        step(6, "Введи <b>цвета</b> через запятую.\n\nНапример: <code>Чёрный,Серый</code>\n"
                "Если цвет один или не важен — отправь «-»."),
        reply_markup=CANCEL_KB,
    )


@router.message(AddProduct.colors)
async def add_colors(message: Message, state: FSMContext):
    t = await need_text(message, "Цвета — текстом.")
    if t is None:
        return
    await state.update_data(colors="" if t in {"-", "—"} else t)
    await state.set_state(AddProduct.photo)
    await message.answer(
        step(7, "Отправь <b>фотографию</b> товара."),
        reply_markup=mk([btn("⏭ Без фото", "addskip")], [btn("❌ Отмена", "adm_cancel")]),
    )


async def _finish_add(message: Message, state: FSMContext, photo_id):
    d = await state.get_data()
    pid = db.add_product(d["name"], d["description"], d["price"], d["category"],
                         d["sizes"], d["colors"], photo_id)
    await state.clear()
    await message.answer("✅ <b>Товар добавлен в каталог</b>")
    await send_card(message, *product_card_view(pid))


@router.message(AddProduct.photo, F.photo)
async def add_photo(message: Message, state: FSMContext):
    await _finish_add(message, state, message.photo[-1].file_id)


@router.callback_query(AddProduct.photo, F.data == "addskip")
async def add_skip_photo(callback: CallbackQuery, state: FSMContext):
    await _finish_add(callback.message, state, None)
    await callback.answer()


@router.message(AddProduct.photo)
async def add_photo_bad(message: Message):
    await message.answer("⚠️ Отправь именно фотографию или нажми «Без фото».")


# =========================
# 📣 РАССЫЛКА
# =========================

@router.callback_query(F.data == "abc")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.content)
    n = len(db.all_user_ids())
    await show_card(
        callback.message,
        title("📣", "РАССЫЛКА") + f"Получателей: <b>{n}</b>\n\n"
        "Отправь сообщение, которое нужно разослать (текст, или фото с подписью).",
        CANCEL_KB,
    )
    await callback.answer()


@router.message(Broadcast.content)
async def broadcast_content(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    n = len(db.all_user_ids())
    await message.answer(
        f"Разослать это сообщение <b>{n}</b> клиентам?",
        reply_markup=mk([btn("🚀 Отправить", "abc_go")], [btn("❌ Отмена", "adm_cancel")]),
    )


@router.callback_query(Broadcast.confirm, F.data == "abc_go")
async def broadcast_go(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await edit_any(callback.message, "⏳ Отправляю…")
    ok = fail = 0
    for uid in db.all_user_ids():
        try:
            await bot.copy_message(uid, data["chat_id"], data["message_id"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await edit_any(
        callback.message,
        f"<b>📣 Рассылка завершена</b>\n\n✅ Доставлено: {ok}\n❌ Не доставлено: {fail}",
        mk([btn("← Админ-панель", "adm")]),
    )
    await callback.answer()
