"""Тонкая обёртка над Telegram Bot API для веб-панели (синхронная, на requests)."""
import hashlib
import io
import os

import requests
from PIL import Image, ImageOps

from config import ADMIN_IDS, BOT_TOKEN, MEDIA_DIR

try:  # необязательно: фото HEIC с iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
MAX_SIDE = 1600


class TgError(Exception):
    """Ошибка Telegram или сети. Текст безопасен для показа (без токена)."""


def _call(method, data=None, files=None, timeout=40):
    try:
        r = requests.post(f"{API}/{method}", data=data, files=files, timeout=timeout)
        j = r.json()
    except requests.RequestException:
        raise TgError("нет связи с Telegram — проверь интернет")
    except ValueError:
        raise TgError("Telegram вернул непонятный ответ")
    if not j.get("ok"):
        raise TgError(j.get("description", "неизвестная ошибка"))
    return j["result"]


def send_message(chat_id, text):
    return _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def send_photo(chat_id, photo, caption=None, silent=False):
    """photo — bytes (загрузка) или строка file_id."""
    data = {"chat_id": chat_id, "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    if silent:
        data["disable_notification"] = "true"
    if isinstance(photo, (bytes, bytearray)):
        return _call("sendPhoto", data, files={"photo": ("photo.jpg", bytes(photo), "image/jpeg")})
    data["photo"] = photo
    return _call("sendPhoto", data)


def photo_file_id(message_result):
    return message_result["photo"][-1]["file_id"]


def upload_photo(data: bytes):
    """Загружает фото в Telegram через чат админа (чтобы получить file_id для бота) и сразу удаляет сообщение."""
    if not ADMIN_IDS:
        raise TgError("в .env не указан ADMIN_ID")
    admin = next(iter(ADMIN_IDS))
    try:
        res = send_photo(admin, data, silent=True)
    except TgError as e:
        raise TgError(f"не удалось загрузить фото ({e}). Открой бота в Telegram и нажми /start")
    file_id = photo_file_id(res)
    try:
        _call("deleteMessage", {"chat_id": admin, "message_id": res["message_id"]})
    except TgError:
        pass
    cache_put(file_id, data)
    return file_id


# ---------- кэш фото для показа в панели ----------

def cache_path(file_id):
    return os.path.join(MEDIA_DIR, hashlib.sha1(file_id.encode()).hexdigest() + ".jpg")


def cache_put(file_id, data: bytes):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    with open(cache_path(file_id), "wb") as f:
        f.write(data)


def fetch_photo(file_id):
    """Путь к файлу в кэше; при необходимости скачивает из Telegram."""
    path = cache_path(file_id)
    if os.path.exists(path):
        return path
    info = _call("getFile", {"file_id": file_id})
    try:
        r = requests.get(f"{FILE_API}/{info['file_path']}", timeout=40)
        r.raise_for_status()
    except requests.RequestException:
        raise TgError("не удалось скачать фото")
    cache_put(file_id, r.content)
    return path


# ---------- подготовка загружаемых картинок ----------

def prepare_image(file_storage) -> bytes:
    """Читает загруженный файл, поворачивает по EXIF, уменьшает и сохраняет как JPEG."""
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
    except Exception:
        raise TgError("не удалось прочитать изображение — используй JPG, PNG или WEBP")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
