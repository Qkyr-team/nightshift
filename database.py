import os
import sqlite3
from contextlib import contextmanager

from config import DB_PATH, LEGACY_DB_PATH

ORDER_STATUSES = [
    ("Новый", "🟡"),
    ("Подтверждён", "🔵"),
    ("У поставщика", "🟣"),
    ("В пути", "🟠"),
    ("Получен", "🟢"),
    ("Отменён", "🔴"),
]
CUSTOM_STATUSES = [
    ("Новая", "🟡"),
    ("В поиске", "🔵"),
    ("Найдено", "🟢"),
    ("Закрыта", "⚫"),
]

ORDER_FILTERS = {
    "new": ("Новый",),
    "work": ("Подтверждён", "У поставщика", "В пути"),
    "done": ("Получен", "Отменён"),
    "all": None,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL,
    category_id INTEGER,
    sizes TEXT NOT NULL DEFAULT '',
    colors TEXT NOT NULL DEFAULT '',
    photo_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    size TEXT NOT NULL,
    color TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 1,
    UNIQUE (user_id, product_id, size, color)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    contact TEXT NOT NULL,
    comment TEXT,
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'Новый',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    size TEXT NOT NULL,
    color TEXT NOT NULL,
    qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    direction TEXT NOT NULL,            -- 'in' от клиента, 'out' от магазина
    text TEXT,
    photo_id TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages (user_id, id);
CREATE TABLE IF NOT EXISTS custom_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    description TEXT NOT NULL,
    photo_id TEXT,
    budget TEXT,
    contact TEXT,
    status TEXT NOT NULL DEFAULT 'Новая',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def fetch(sql, params=(), one=False):
    with db() as c:
        cur = c.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()


def run(sql, params=()):
    with db() as c:
        return c.execute(sql, params).lastrowid


def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")  # бот и веб-панель работают с базой одновременно
        c.executescript(SCHEMA)
    migrate_legacy()


def migrate_legacy():
    """Переносит товары и заявки из старой базы nightshift.db (один раз)."""
    if not os.path.exists(LEGACY_DB_PATH):
        return
    if fetch("SELECT COUNT(*) AS n FROM products", one=True)["n"]:
        return
    src = sqlite3.connect(LEGACY_DB_PATH)
    src.row_factory = sqlite3.Row
    try:
        for p in src.execute("SELECT * FROM products"):
            add_product(p["name"], p["description"], p["price"], p["category"],
                        p["sizes"], p["colors"], p["photo_id"])
        for r in src.execute("SELECT * FROM custom_orders"):
            run(
                "INSERT INTO custom_orders (user_id, username, description, budget, contact, status)"
                " VALUES (?,?,?,?,?,?)",
                (r["user_id"], r["username"], r["description"], r["budget"], r["contact"], r["status"]),
            )
    except sqlite3.Error:
        pass
    finally:
        src.close()


# ---------- users ----------

def upsert_user(user_id, username, first_name):
    run(
        "INSERT INTO users (user_id, username, first_name) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
        (user_id, username, first_name),
    )


def all_user_ids():
    return [r["user_id"] for r in fetch("SELECT user_id FROM users")]


def get_user(user_id):
    return fetch("SELECT * FROM users WHERE user_id = ?", (user_id,), one=True)


# ---------- сообщения (переписка с клиентами) ----------

def add_message(user_id, direction, text=None, photo_id=None):
    return run(
        "INSERT INTO messages (user_id, direction, text, photo_id, is_read) VALUES (?,?,?,?,?)",
        (user_id, direction, text, photo_id, 0 if direction == "in" else 1),
    )


def get_thread(user_id, limit=300):
    rows = fetch("SELECT * FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))


def mark_thread_read(user_id):
    run("UPDATE messages SET is_read = 1 WHERE user_id = ? AND direction = 'in' AND is_read = 0", (user_id,))


def count_unread():
    """Сколько диалогов с непрочитанными сообщениями."""
    return fetch("SELECT COUNT(DISTINCT user_id) AS n FROM messages WHERE direction = 'in' AND is_read = 0",
                 one=True)["n"]


def list_conversations():
    return fetch(
        "SELECT m.user_id, u.username, u.first_name, MAX(m.id) AS last_id, MAX(m.created_at) AS last_at, "
        "SUM(CASE WHEN m.direction = 'in' AND m.is_read = 0 THEN 1 ELSE 0 END) AS unread, "
        "(SELECT text FROM messages WHERE user_id = m.user_id ORDER BY id DESC LIMIT 1) AS last_text, "
        "(SELECT photo_id FROM messages WHERE user_id = m.user_id ORDER BY id DESC LIMIT 1) AS last_photo, "
        "(SELECT direction FROM messages WHERE user_id = m.user_id ORDER BY id DESC LIMIT 1) AS last_dir "
        "FROM messages m LEFT JOIN users u ON u.user_id = m.user_id "
        "GROUP BY m.user_id ORDER BY last_id DESC"
    )


# ---------- categories ----------

def get_or_create_category(name):
    name = name.strip()
    row = fetch("SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (name,), one=True)
    if row:
        return row["id"]
    return run("INSERT INTO categories (name) VALUES (?)", (name,))


def get_category(cat_id):
    return fetch("SELECT * FROM categories WHERE id = ?", (cat_id,), one=True)


def get_categories_with_counts():
    """Для клиентов: только категории, где есть видимые товары."""
    return fetch(
        "SELECT c.id, c.name, COUNT(p.id) AS cnt FROM categories c "
        "JOIN products p ON p.category_id = c.id AND p.active = 1 "
        "GROUP BY c.id ORDER BY c.name"
    )


def get_categories_admin():
    return fetch(
        "SELECT c.id, c.name, COUNT(p.id) AS cnt FROM categories c "
        "LEFT JOIN products p ON p.category_id = c.id GROUP BY c.id ORDER BY c.name"
    )


def cleanup_categories():
    run("DELETE FROM categories WHERE id NOT IN "
        "(SELECT DISTINCT category_id FROM products WHERE category_id IS NOT NULL)")


# ---------- products ----------

PRODUCT_FIELDS = {"name", "description", "price", "category_id", "sizes", "colors", "photo_id", "active"}


def add_product(name, description, price, category, sizes, colors, photo_id):
    cat_id = get_or_create_category(category)
    return run(
        "INSERT INTO products (name, description, price, category_id, sizes, colors, photo_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (name, description, price, cat_id, sizes, colors, photo_id),
    )


def get_product(pid):
    return fetch(
        "SELECT p.*, c.name AS category FROM products p "
        "LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?",
        (pid,), one=True,
    )


def list_products_all():
    return fetch(
        "SELECT p.*, c.name AS category FROM products p "
        "LEFT JOIN categories c ON c.id = p.category_id ORDER BY c.name, p.id DESC"
    )


def get_products(category_id, only_active=True):
    sql = "SELECT * FROM products WHERE category_id = ?"
    if only_active:
        sql += " AND active = 1"
    return fetch(sql + " ORDER BY id DESC", (category_id,))


def update_product(pid, **fields):
    keys = [k for k in fields if k in PRODUCT_FIELDS]
    if not keys:
        return
    sets = ", ".join(f"{k} = ?" for k in keys)
    run(f"UPDATE products SET {sets} WHERE id = ?", (*[fields[k] for k in keys], pid))
    cleanup_categories()


def set_product_category(pid, category_name):
    update_product(pid, category_id=get_or_create_category(category_name))


def toggle_product(pid):
    run("UPDATE products SET active = 1 - active WHERE id = ?", (pid,))


def delete_product(pid):
    run("DELETE FROM products WHERE id = ?", (pid,))
    run("DELETE FROM cart WHERE product_id = ?", (pid,))
    cleanup_categories()


# ---------- cart ----------

MAX_QTY = 10


def add_to_cart(user_id, product_id, size, color):
    run(
        "INSERT INTO cart (user_id, product_id, size, color, qty) VALUES (?,?,?,?,1) "
        "ON CONFLICT(user_id, product_id, size, color) DO UPDATE SET qty = MIN(qty + 1, ?)",
        (user_id, product_id, size, color, MAX_QTY),
    )


def get_cart(user_id):
    return fetch(
        "SELECT c.id, c.product_id, c.size, c.color, c.qty, p.name, p.price "
        "FROM cart c JOIN products p ON p.id = c.product_id "
        "WHERE c.user_id = ? AND p.active = 1 ORDER BY c.id",
        (user_id,),
    )


def change_qty(cart_id, user_id, delta):
    run("UPDATE cart SET qty = MIN(qty + ?, ?) WHERE id = ? AND user_id = ?",
        (delta, MAX_QTY, cart_id, user_id))
    run("DELETE FROM cart WHERE id = ? AND user_id = ? AND qty <= 0", (cart_id, user_id))


def remove_cart_item(cart_id, user_id):
    run("DELETE FROM cart WHERE id = ? AND user_id = ?", (cart_id, user_id))


def clear_cart(user_id):
    run("DELETE FROM cart WHERE user_id = ?", (user_id,))


# ---------- orders ----------

def create_order_from_cart(user_id, username, first_name, contact, comment):
    with db() as c:
        items = c.execute(
            "SELECT c.product_id, c.size, c.color, c.qty, p.name, p.price "
            "FROM cart c JOIN products p ON p.id = c.product_id "
            "WHERE c.user_id = ? AND p.active = 1",
            (user_id,),
        ).fetchall()
        if not items:
            return None
        total = sum(i["price"] * i["qty"] for i in items)
        oid = c.execute(
            "INSERT INTO orders (user_id, username, first_name, contact, comment, total)"
            " VALUES (?,?,?,?,?,?)",
            (user_id, username, first_name, contact, comment, total),
        ).lastrowid
        c.executemany(
            "INSERT INTO order_items (order_id, product_id, name, price, size, color, qty)"
            " VALUES (?,?,?,?,?,?,?)",
            [(oid, i["product_id"], i["name"], i["price"], i["size"], i["color"], i["qty"]) for i in items],
        )
        c.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
        return oid


def get_order(oid):
    return fetch("SELECT * FROM orders WHERE id = ?", (oid,), one=True)


def get_order_items(oid):
    return fetch("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (oid,))


def get_user_orders(user_id, limit=10):
    return fetch("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))


def _filter_sql(flt):
    statuses = ORDER_FILTERS.get(flt)
    if not statuses:
        return "", ()
    return f" WHERE status IN ({','.join('?' * len(statuses))})", statuses


def count_orders(flt="all"):
    where, params = _filter_sql(flt)
    return fetch(f"SELECT COUNT(*) AS n FROM orders{where}", params, one=True)["n"]


def list_orders(flt, limit, offset):
    where, params = _filter_sql(flt)
    return fetch(f"SELECT * FROM orders{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                 (*params, limit, offset))


def update_order_status(oid, status):
    run("UPDATE orders SET status = ? WHERE id = ?", (status, oid))


# ---------- custom orders ----------

def create_custom_order(user_id, username, first_name, description, photo_id, budget, contact):
    return run(
        "INSERT INTO custom_orders (user_id, username, first_name, description, photo_id, budget, contact)"
        " VALUES (?,?,?,?,?,?,?)",
        (user_id, username, first_name, description, photo_id, budget, contact),
    )


def get_custom_order(rid):
    return fetch("SELECT * FROM custom_orders WHERE id = ?", (rid,), one=True)


def count_custom_orders():
    return fetch("SELECT COUNT(*) AS n FROM custom_orders", one=True)["n"]


def list_custom_orders(limit, offset):
    return fetch("SELECT * FROM custom_orders ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))


def update_custom_status(rid, status):
    run("UPDATE custom_orders SET status = ? WHERE id = ?", (status, rid))


# ---------- stats ----------

def stats():
    def n(sql, params=()):
        return fetch(sql, params, one=True)["n"]

    return {
        "users": n("SELECT COUNT(*) AS n FROM users"),
        "products": n("SELECT COUNT(*) AS n FROM products"),
        "hidden": n("SELECT COUNT(*) AS n FROM products WHERE active = 0"),
        "orders": n("SELECT COUNT(*) AS n FROM orders"),
        "new_orders": n("SELECT COUNT(*) AS n FROM orders WHERE status = 'Новый'"),
        "new_custom": n("SELECT COUNT(*) AS n FROM custom_orders WHERE status = 'Новая'"),
        "revenue": n("SELECT COALESCE(SUM(total), 0) AS n FROM orders WHERE status != 'Отменён'"),
    }
