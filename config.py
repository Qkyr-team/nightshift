import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ADMIN_ID=111  или  ADMIN_ID=111,222
ADMIN_IDS = {
    int(x)
    for x in os.getenv("ADMIN_ID", "").replace(";", ",").split(",")
    if x.strip().lstrip("-").isdigit()
}

SHOP_NAME = os.getenv("SHOP_NAME", "NIGHTSHIFT")
CURRENCY = os.getenv("CURRENCY", "€")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Vilnius")

DB_PATH = os.path.join(BASE_DIR, "shop.db")
LEGACY_DB_PATH = os.path.join(BASE_DIR, "nightshift.db")  # старая база (подтянется автоматически)
BANNER_PATH = os.path.join(BASE_DIR, "assets", "banner.jpg")

# ---------- веб-панель управления ----------
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "").strip()   # без пароля панель не запускается
PANEL_HOST = os.getenv("PANEL_HOST", "127.0.0.1").strip()  # 127.0.0.1 = доступна только на этом компьютере
PANEL_PORT = int(os.getenv("PANEL_PORT", "8000"))
PANEL_SECRET = os.getenv("PANEL_SECRET", "").strip()
MEDIA_DIR = os.path.join(BASE_DIR, "media")                # кэш фото для панели
