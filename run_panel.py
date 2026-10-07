"""Запуск только веб-панели (без бота): python3 run_panel.py"""
import sys

from config import PANEL_HOST, PANEL_PASSWORD, PANEL_PORT
from database import init_db

if not PANEL_PASSWORD:
    sys.exit("❌ В .env не задан PANEL_PASSWORD. Добавь строку PANEL_PASSWORD=твой-пароль")

from panel.app import create_app  # noqa: E402

if __name__ == "__main__":
    init_db()
    print(f"Панель: http://{PANEL_HOST}:{PANEL_PORT}")
    create_app().run(host=PANEL_HOST, port=PANEL_PORT, threaded=True)
