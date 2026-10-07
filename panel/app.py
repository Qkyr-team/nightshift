import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import database as db
from config import (
    BOT_TOKEN,
    PANEL_HOST,
    PANEL_PASSWORD,
    PANEL_PORT,
    PANEL_SECRET,
    SHOP_NAME,
)
from database import CUSTOM_STATUSES, ORDER_FILTERS, ORDER_STATUSES
from shared import (
    CUSTOM_NOTES,
    LINE,
    ORDER_NOTES,
    client_message,
    contact_url,
    esc,
    fmt_dt,
    money,
    order_no,
    split_list,
    status_emoji,
)

from . import tgapi
from .tgapi import TgError

log = logging.getLogger("panel")

PER_PAGE = 15
STATUS_CLASS = {
    "Новый": "yellow", "Подтверждён": "blue", "У поставщика": "purple",
    "В пути": "orange", "Получен": "green", "Отменён": "red",
    "Новая": "yellow", "В поиске": "blue", "Найдено": "green", "Закрыта": "gray",
}
FILTER_TABS = [("new", "Новые"), ("work", "В работе"), ("done", "Архив"), ("all", "Все")]
FILE_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,250}")


def create_app():
    app = Flask(__name__)
    app.secret_key = PANEL_SECRET or hashlib.sha256(f"{BOT_TOKEN}|{PANEL_PASSWORD}".encode()).hexdigest()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        TEMPLATES_AUTO_RELOAD=False,
    )
    local_only = PANEL_HOST in ("127.0.0.1", "localhost", "::1")
    login_fails = {"n": 0, "t": 0.0}

    # ---------- шаблонные помощники ----------
    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        status_class=lambda s: STATUS_CLASS.get(s, "gray"),
        status_emoji=status_emoji,
        order_statuses=ORDER_STATUSES,
        custom_statuses=CUSTOM_STATUSES,
        shop_name=SHOP_NAME,
        contact_url=contact_url,
        split_list=split_list,
        order_no=order_no,
        money=money,
    )
    app.add_template_filter(fmt_dt, "dt")
    app.add_template_filter(order_no, "ono")
    app.add_template_filter(money, "money")

    @app.context_processor
    def inject_nav():
        if not session.get("auth"):
            return {}
        s = db.stats()
        return {"nav": {"orders": s["new_orders"], "custom": s["new_custom"], "unread": db.count_unread()}}

    # ---------- защита: вход, CSRF, хост ----------
    @app.before_request
    def guard():
        if local_only and request.host.split(":")[0] not in ("127.0.0.1", "localhost", "[::1]"):
            abort(400)
        if request.method == "POST":
            sent = request.form.get("_csrf", "")
            if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Страница устарела. Обнови её и попробуй ещё раз.")
        if request.endpoint in ("login", "static", None):
            return None
        if not session.get("auth"):
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        return None

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(e):
        msg = {413: "Файл слишком большой."}.get(getattr(e, "code", 0), getattr(e, "description", ""))
        return render_template("error.html", code=getattr(e, "code", 500), message=msg), getattr(e, "code", 500)

    def safe_next(default):
        nxt = request.form.get("next") or request.args.get("next") or ""
        return nxt if nxt.startswith("/") and not nxt.startswith("//") else default

    def uid_known(uid):
        return bool(db.get_user(uid) or db.get_thread(uid, 1) or db.get_user_orders(uid, 1))

    # ---------- вход / выход ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if login_fails["n"] >= 5 and time.time() - login_fails["t"] < 30:
                flash("Слишком много попыток. Подожди полминуты.", "error")
            elif hmac.compare_digest(request.form.get("password", ""), PANEL_PASSWORD):
                login_fails["n"] = 0
                session.clear()
                session["auth"] = True
                session.permanent = True
                return redirect(safe_next(url_for("dashboard")))
            else:
                login_fails.update(n=login_fails["n"] + 1, t=time.time())
                time.sleep(1)
                flash("Неверный пароль.", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- обзор ----------
    @app.get("/")
    def dashboard():
        s = db.stats()
        recent = [{"o": o, "items": db.get_order_items(o["id"])} for o in db.list_orders("all", 6, 0)]
        convs = db.list_conversations()[:6]
        return render_template("dashboard.html", s=s, recent=recent, convs=convs,
                               today=datetime.now().strftime("%d.%m.%Y"))

    # ---------- заказы ----------
    @app.get("/orders")
    def orders():
        flt = request.args.get("f", "new")
        if flt not in ORDER_FILTERS:
            flt = "new"
        page = max(request.args.get("page", 1, type=int), 1)
        total = db.count_orders(flt)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(page, pages)
        rows = [{"o": o, "items": db.get_order_items(o["id"])}
                for o in db.list_orders(flt, PER_PAGE, (page - 1) * PER_PAGE)]
        counts = {k: db.count_orders(k) for k in ORDER_FILTERS}
        return render_template("orders.html", rows=rows, flt=flt, tabs=FILTER_TABS, counts=counts,
                               page=page, pages=pages, total=total)

    @app.get("/orders/<int:oid>")
    def order(oid):
        o = db.get_order(oid)
        if not o:
            abort(404)
        return render_template("order.html", o=o, items=db.get_order_items(oid),
                               user=db.get_user(o["user_id"]), thread=db.get_thread(o["user_id"], 6))

    @app.post("/orders/<int:oid>/status")
    def order_status(oid):
        o = db.get_order(oid)
        status = request.form.get("status", "")
        if not o or status not in dict(ORDER_STATUSES):
            abort(400)
        if o["status"] != status:
            db.update_order_status(oid, status)
            flash(f"Статус заказа {order_no(oid)}: {status}", "ok")
            note = ORDER_NOTES.get(status)
            if note and request.form.get("notify"):
                try:
                    tgapi.send_message(
                        o["user_id"],
                        f"<b>📦 Заказ {order_no(oid)}</b>\n{status_emoji(status)} <b>{esc(status)}</b>\n\n{note}")
                    flash("Клиент получил уведомление.", "ok")
                except TgError as e:
                    flash(f"Статус изменён, но уведомить клиента не удалось: {e}", "error")
        return redirect(url_for("order", oid=oid))

    # ---------- товары ----------
    @app.get("/products")
    def products():
        groups = {}
        for p in db.list_products_all():
            groups.setdefault(p["category"] or "Без категории", []).append(p)
        return render_template("products.html", groups=groups, total=sum(len(v) for v in groups.values()))

    def _product_form_data():
        f = request.form
        data = {
            "name": f.get("name", "").strip(),
            "description": f.get("description", "").strip(),
            "category": f.get("category", "").strip()[:40],
            "sizes": ",".join(split_list(f.get("sizes", ""))),
            "colors": ",".join(split_list(f.get("colors", ""))),
            "price_raw": f.get("price", "").strip(),
            "active": 1 if f.get("active") else 0,
        }
        errors = []
        if not data["name"]:
            errors.append("Укажи название.")
        if not data["category"]:
            errors.append("Укажи категорию.")
        try:
            data["price"] = float(data["price_raw"].replace(",", ".").replace("€", ""))
            if data["price"] <= 0:
                raise ValueError
        except ValueError:
            errors.append("Цена должна быть числом, например 59.90.")
        return data, errors

    def _product_page(p, errors=None):
        cats = [c["name"] for c in db.get_categories_admin()]
        for e in errors or []:
            flash(e, "error")
        return render_template("product_form.html", p=p, cats=cats)

    @app.route("/products/new", methods=["GET", "POST"])
    def product_new():
        if request.method == "GET":
            return _product_page({"active": 1})
        data, errors = _product_form_data()
        photo_id = None
        file = request.files.get("photo")
        if not errors and file and file.filename:
            try:
                photo_id = tgapi.upload_photo(tgapi.prepare_image(file))
            except TgError as e:
                errors.append(f"Фото: {e}")
        if errors:
            data["price"] = data["price_raw"]
            return _product_page(data, errors)
        pid = db.add_product(data["name"], data["description"], data["price"], data["category"],
                             data["sizes"], data["colors"], photo_id)
        if not data["active"]:
            db.toggle_product(pid)
        flash(f"Товар «{data['name']}» добавлен в каталог.", "ok")
        return redirect(url_for("products"))

    @app.route("/products/<int:pid>", methods=["GET", "POST"])
    def product_edit(pid):
        p = db.get_product(pid)
        if not p:
            abort(404)
        if request.method == "GET":
            return _product_page(dict(p))
        data, errors = _product_form_data()
        photo_id = p["photo_id"]
        file = request.files.get("photo")
        if not errors and file and file.filename:
            try:
                photo_id = tgapi.upload_photo(tgapi.prepare_image(file))
            except TgError as e:
                errors.append(f"Фото: {e}")
        elif request.form.get("remove_photo"):
            photo_id = None
        if errors:
            data.update(id=pid, photo_id=p["photo_id"], price=data["price_raw"])
            return _product_page(data, errors)
        db.set_product_category(pid, data["category"])
        db.update_product(pid, name=data["name"], description=data["description"], price=data["price"],
                          sizes=data["sizes"], colors=data["colors"], photo_id=photo_id, active=data["active"])
        flash("Изменения сохранены.", "ok")
        return redirect(url_for("products"))

    @app.post("/products/<int:pid>/toggle")
    def product_toggle(pid):
        if not db.get_product(pid):
            abort(404)
        db.toggle_product(pid)
        return redirect(url_for("products"))

    @app.post("/products/<int:pid>/delete")
    def product_delete(pid):
        p = db.get_product(pid)
        if not p:
            abort(404)
        db.delete_product(pid)
        flash(f"Товар «{p['name']}» удалён.", "ok")
        return redirect(url_for("products"))

    # ---------- сообщения ----------
    @app.get("/messages")
    def messages_index():
        convs = db.list_conversations()
        if convs:
            return redirect(url_for("thread", uid=convs[0]["user_id"]))
        return render_template("messages.html", convs=[], uid=None, thread=[], user=None, orders=[])

    @app.get("/messages/<int:uid>")
    def thread(uid):
        if not uid_known(uid):
            abort(404)
        db.mark_thread_read(uid)
        return render_template("messages.html", convs=db.list_conversations(), uid=uid,
                               thread=db.get_thread(uid), user=db.get_user(uid),
                               orders=db.get_user_orders(uid, 5))

    @app.post("/send")
    def send():
        uid = request.form.get("user_id", type=int)
        text = request.form.get("text", "").strip()
        file = request.files.get("photo")
        back = safe_next(url_for("thread", uid=uid or 0))
        if not uid or not uid_known(uid):
            abort(400)
        has_photo = bool(file and file.filename)
        if not text and not has_photo:
            flash("Напиши сообщение или приложи фото.", "error")
            return redirect(back)
        if len(text) > 3500:
            flash("Слишком длинное сообщение (максимум 3500 символов).", "error")
            return redirect(back)
        photo_id = None
        try:
            if has_photo:
                data = tgapi.prepare_image(file)
                caption = client_message(SHOP_NAME, text) if text else None
                if caption and len(caption) > 1000:
                    res = tgapi.send_photo(uid, data)
                    tgapi.send_message(uid, caption)
                else:
                    res = tgapi.send_photo(uid, data, caption)
                photo_id = tgapi.photo_file_id(res)
                tgapi.cache_put(photo_id, data)
            else:
                tgapi.send_message(uid, client_message(SHOP_NAME, text))
        except TgError as e:
            flash(f"Не удалось отправить: {e}", "error")
            return redirect(back)
        db.add_message(uid, "out", text, photo_id)
        db.mark_thread_read(uid)
        return redirect(back)

    # ---------- заявки «под заказ» ----------
    @app.get("/custom")
    def custom_list():
        return render_template("custom.html", rows=db.list_custom_orders(100, 0))

    @app.get("/custom/<int:rid>")
    def custom_detail(rid):
        r = db.get_custom_order(rid)
        if not r:
            abort(404)
        return render_template("custom_detail.html", r=r, user=db.get_user(r["user_id"]),
                               thread=db.get_thread(r["user_id"], 6))

    @app.post("/custom/<int:rid>/status")
    def custom_status(rid):
        r = db.get_custom_order(rid)
        status = request.form.get("status", "")
        if not r or status not in dict(CUSTOM_STATUSES):
            abort(400)
        if r["status"] != status:
            db.update_custom_status(rid, status)
            flash(f"Статус заявки {order_no(rid)}: {status}", "ok")
            note = CUSTOM_NOTES.get(status)
            if note and request.form.get("notify"):
                try:
                    tgapi.send_message(
                        r["user_id"],
                        f"<b>🔎 Заявка {order_no(rid)}</b>\n{status_emoji(status, True)} <b>{esc(status)}</b>\n\n{note}")
                    flash("Клиент получил уведомление.", "ok")
                except TgError as e:
                    flash(f"Статус изменён, но уведомить клиента не удалось: {e}", "error")
        return redirect(url_for("custom_detail", rid=rid))

    # ---------- рассылка ----------
    @app.route("/broadcast", methods=["GET", "POST"])
    def broadcast():
        users = db.all_user_ids()
        if request.method == "GET":
            return render_template("broadcast.html", n=len(users))
        text = request.form.get("text", "").strip()
        file = request.files.get("photo")
        has_photo = bool(file and file.filename)
        if not text and not has_photo:
            flash("Напиши текст или приложи фото.", "error")
            return redirect(url_for("broadcast"))
        try:
            file_id = tgapi.upload_photo(tgapi.prepare_image(file)) if has_photo else None
        except TgError as e:
            flash(f"Фото: {e}", "error")
            return redirect(url_for("broadcast"))
        body = client_message(SHOP_NAME, text) if text else None
        ok = fail = 0
        for uid in users:
            try:
                if file_id and body and len(body) <= 1000:
                    tgapi.send_photo(uid, file_id, body)
                elif file_id:
                    tgapi.send_photo(uid, file_id)
                    if body:
                        tgapi.send_message(uid, body)
                else:
                    tgapi.send_message(uid, body)
                ok += 1
            except TgError:
                fail += 1
            time.sleep(0.05)
        flash(f"Рассылка завершена: доставлено {ok}, не доставлено {fail}.", "ok" if ok else "error")
        return redirect(url_for("broadcast"))

    # ---------- фото и служебное ----------
    @app.get("/photo/<file_id>")
    def photo(file_id):
        if not FILE_ID_RE.fullmatch(file_id):
            abort(404)
        try:
            path = tgapi.fetch_photo(file_id)
        except TgError:
            abort(404)
        return send_file(path, mimetype="image/jpeg", max_age=60 * 60 * 24 * 30)

    @app.get("/api/counts")
    def api_counts():
        s = db.stats()
        return jsonify(orders=s["new_orders"], custom=s["new_custom"], unread=db.count_unread())

    return app


def start_in_thread(host=None, port=None):
    """Запускает панель в фоновом потоке (вместе с ботом)."""
    from werkzeug.serving import make_server

    host, port = host or PANEL_HOST, port or PANEL_PORT
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    server = make_server(host, port, create_app(), threaded=True)
    threading.Thread(target=server.serve_forever, name="panel", daemon=True).start()
    return server
