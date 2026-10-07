from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

import database as db
from config import SHOP_NAME
from utils import (
    BTN_CATALOG,
    LINE,
    btn,
    chunk,
    edit_any,
    esc,
    mk,
    money,
    show_card,
    split_list,
    title,
)

router = Router()


# ---------- категории ----------

def categories_view():
    cats = db.get_categories_with_counts()
    if not cats:
        return (title("🛍", "КАТАЛОГ") + "Пока здесь пусто. Загляни чуть позже 🖤",
                mk([btn("← Меню", "back_to_menu")]))
    rows = [[btn(f"▫️ {c['name']}  ·  {c['cnt']}", f"cat:{c['id']}")] for c in cats]
    rows.append([btn("🛒 Корзина", "cart")])
    return title("🛍", "КАТАЛОГ") + "Выбери категорию:", mk(*rows)


@router.message(F.text == BTN_CATALOG)
async def catalog_message(message: Message):
    text, markup = categories_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery):
    text, markup = categories_view()
    await show_card(callback.message, text, markup)
    await callback.answer()


# ---------- карточка товара с листанием ----------

def product_view(products, idx):
    p = products[idx]
    total = len(products)
    sizes = " · ".join(split_list(p["sizes"])) or "—"
    colors = " · ".join(split_list(p["colors"])) or "—"
    text = (
        f"<b>🖤 {esc(p['name'])}</b>\n{LINE}\n\n"
        f"{esc(p['description'])}\n\n"
        f"<b>💶 {money(p['price'])}</b>\n\n"
        f"📏 <b>Размеры:</b> {esc(sizes)}\n"
        f"🎨 <b>Цвета:</b> {esc(colors)}\n\n"
        f"{LINE}\n{esc(SHOP_NAME)}"
    )
    rows = [[btn("🛒 В корзину", f"add:{p['id']}")]]
    if total > 1:
        cat = p["category_id"]
        rows.append([
            btn("◀", f"p:{cat}:{(idx - 1) % total}"),
            btn(f"{idx + 1} / {total}", "noop"),
            btn("▶", f"p:{cat}:{(idx + 1) % total}"),
        ])
    rows.append([btn("← Категории", "catalog")])
    return text, mk(*rows), p["photo_id"]


@router.callback_query(F.data.startswith(("cat:", "p:")))
async def open_category(callback: CallbackQuery):
    parts = callback.data.split(":")
    cat_id = int(parts[1])
    idx = int(parts[2]) if len(parts) > 2 else 0
    products = db.get_products(cat_id)
    if not products:
        await callback.answer("В этой категории пока ничего нет.", show_alert=True)
        return
    text, markup, photo = product_view(products, idx % len(products))
    await show_card(callback.message, text, markup, photo)
    await callback.answer()


@router.callback_query(F.data.startswith("pv:"))
async def view_product(callback: CallbackQuery):
    p = db.get_product(int(callback.data.split(":")[1]))
    if not p or not p["active"]:
        await callback.answer("Товар недоступен.", show_alert=True)
        return
    products = db.get_products(p["category_id"])
    idx = next((i for i, x in enumerate(products) if x["id"] == p["id"]), 0)
    text, markup, photo = product_view(products, idx)
    await show_card(callback.message, text, markup, photo)
    await callback.answer()


# ---------- выбор размера и цвета -> корзина ----------

async def _pick(callback, p, header, options, prefix):
    rows = chunk([btn(o, f"{prefix}:{i}") for i, o in enumerate(options)], 4)
    rows.append([btn("← Назад", f"pv:{p['id']}")])
    text = f"<b>🖤 {esc(p['name'])}</b>\n{LINE}\n\n{header}"
    await edit_any(callback.message, text, mk(*rows))


async def _add_flow(callback: CallbackQuery, pid: int, si=None, ci=None):
    p = db.get_product(pid)
    if not p or not p["active"]:
        await callback.answer("Товар недоступен.", show_alert=True)
        return
    sizes, colors = split_list(p["sizes"]), split_list(p["colors"])

    if si is None:
        if len(sizes) > 1:
            await _pick(callback, p, "📏 <b>Выбери размер:</b>", sizes, f"sz:{pid}")
            await callback.answer()
            return
        si = 0
    if ci is None:
        if len(colors) > 1:
            await _pick(callback, p, "🎨 <b>Выбери цвет:</b>", colors, f"cl:{pid}:{si}")
            await callback.answer()
            return
        ci = 0

    try:
        size = sizes[si] if sizes else "—"
        color = colors[ci] if colors else "—"
    except IndexError:
        await callback.answer("Кнопка устарела, открой товар заново.", show_alert=True)
        return

    db.add_to_cart(callback.from_user.id, pid, size, color)
    text = (f"<b>✅ ДОБАВЛЕНО В КОРЗИНУ</b>\n{LINE}\n\n"
            f"<b>{esc(p['name'])}</b>\n{esc(size)} · {esc(color)}")
    await edit_any(callback.message, text, mk(
        [btn("🛒 Открыть корзину", "cart")],
        [btn("🛍 Продолжить покупки", f"pv:{pid}")],
    ))
    await callback.answer("Добавлено ✅")


@router.callback_query(F.data.startswith("add:"))
async def add_start(callback: CallbackQuery):
    await _add_flow(callback, int(callback.data.split(":")[1]))


@router.callback_query(F.data.startswith("sz:"))
async def add_size(callback: CallbackQuery):
    _, pid, si = callback.data.split(":")
    await _add_flow(callback, int(pid), si=int(si))


@router.callback_query(F.data.startswith("cl:"))
async def add_color(callback: CallbackQuery):
    _, pid, si, ci = callback.data.split(":")
    await _add_flow(callback, int(pid), si=int(si), ci=int(ci))
