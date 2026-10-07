import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import database as db
from config import ADMIN_IDS, BANNER_PATH, SHOP_NAME
from handlers.orders import forward_support
from utils import (
    BTN_ADMIN,
    BTN_CART,
    BTN_CATALOG,
    BTN_CUSTOM,
    BTN_ORDERS,
    BTN_SUPPORT,
    LINE,
    edit_any,
)

log = logging.getLogger(__name__)

router = Router()
fallback = Router()  # подключается последним

HOME_TEXT = (
    f"<b>🌙 {SHOP_NAME}</b>\n{LINE}\n\n"
    "Одежда для тех, кто живёт ночью.\n"
    "Выбирай вещь, оформляй заказ — мы напишем тебе в Telegram.\n\n"
    "🛍 <b>Каталог</b> — вся одежда\n"
    "🔎 <b>Заказать под себя</b> — найдём любую вещь\n\n"
    "<i>Выбери раздел в меню ниже 👇</i>"
)

_banner_file_id = None


def main_menu(user_id: int):
    rows = [
        [KeyboardButton(text=BTN_CATALOG), KeyboardButton(text=BTN_CART)],
        [KeyboardButton(text=BTN_ORDERS), KeyboardButton(text=BTN_CUSTOM)],
        [KeyboardButton(text=BTN_SUPPORT)],
    ]
    if user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    global _banner_file_id
    await state.clear()
    u = message.from_user
    db.upsert_user(u.id, u.username, u.full_name)
    markup = main_menu(u.id)

    if os.path.exists(BANNER_PATH):
        try:
            photo = _banner_file_id or FSInputFile(BANNER_PATH)
            sent = await message.answer_photo(photo, caption=HOME_TEXT, reply_markup=markup)
            if not _banner_file_id:
                _banner_file_id = sent.photo[-1].file_id
            return
        except Exception as e:
            log.warning("Баннер не отправился: %s", e)
    await message.answer(HOME_TEXT, reply_markup=markup)


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Выбери раздел в меню 👇", reply_markup=main_menu(message.from_user.id))


@router.callback_query(F.data == "cancel_state")
async def cancel_state(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_any(callback.message, "Отменено.")
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(HOME_TEXT, reply_markup=main_menu(callback.from_user.id))
    await callback.answer()


# ---------- запасные обработчики (самые последние) ----------

@fallback.message(F.text | F.photo)
async def free_message(message: Message, bot: Bot):
    """Любое сообщение вне сценария — вопрос магазину (чтобы переписка шла как в обычном чате)."""
    if message.from_user.id in ADMIN_IDS or (message.text or "").startswith("/"):
        await message.answer("Не понял 🤔 Выбери раздел в меню внизу 👇")
        return
    await forward_support(message, bot)
    await message.answer("✅ Передали сообщение. Мы ответим тебе здесь.")


@fallback.callback_query()
async def stale_button(callback: CallbackQuery):
    await callback.answer()
