import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram import BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import ADMIN_IDS, BOT_TOKEN, PANEL_HOST, PANEL_PASSWORD, PANEL_PORT, SHOP_NAME
from database import init_db
from handlers import admin, cart, catalog, orders, start
from utils import MENU_TEXTS


class ResetStateOnMenu(BaseMiddleware):
    """Если человек нажал кнопку меню посреди диалога — сбрасываем незаконченный шаг."""

    async def __call__(self, handler, event, data):
        if getattr(event, "text", None) in MENU_TEXTS:
            state = data.get("state")
            if state:
                await state.clear()
        return await handler(event, data)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not BOT_TOKEN:
        sys.exit("❌ BOT_TOKEN не найден. Заполни файл .env (см. .env.example).")
    if not ADMIN_IDS:
        logging.warning("ADMIN_ID не задан в .env — админ-панель будет недоступна.")

    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.filter(F.chat.type == "private")
    dp.message.outer_middleware(ResetStateOnMenu())

    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(cart.router)
    dp.include_router(orders.router)
    dp.include_router(admin.router)
    dp.include_router(start.fallback)  # всегда последним

    await bot.set_my_commands([
        BotCommand(command="start", description=f"Открыть {SHOP_NAME}"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)

    panel_url = None
    if PANEL_PASSWORD:
        try:
            from panel.app import start_in_thread

            start_in_thread()
            panel_url = f"http://{PANEL_HOST}:{PANEL_PORT}"
        except OSError as e:
            logging.error("Панель не запустилась (порт %s занят?): %s", PANEL_PORT, e)
    else:
        logging.warning("PANEL_PASSWORD не задан в .env — веб-панель выключена.")

    print("━━━━━━━━━━━━━━━━━━━━")
    print(f"   {SHOP_NAME} BOT")
    print("   Бот запущен")
    if panel_url:
        print(f"   Панель: {panel_url}")
    print("━━━━━━━━━━━━━━━━━━━━")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
