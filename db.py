from __future__ import annotations

import csv
import sqlite3
import uuid
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "parrilla.db"
MENU_CSV_PATH = BASE_DIR / "carta.csv"
ALLOWED_ORDER_STATUSES = {"open", "confirmed", "closed"}
INSERT_ORDER_MEMBER_SQL = "INSERT OR IGNORE INTO order_members (order_id, user_id) VALUES (?, ?)"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name)
            );

            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, name)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                access_key TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'open',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS order_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, user_id),
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                menu_item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(menu_item_id) REFERENCES menu_items(id) ON DELETE RESTRICT
            );

            CREATE TRIGGER IF NOT EXISTS trg_orders_updated_at
            AFTER UPDATE ON orders
            FOR EACH ROW
            BEGIN
                UPDATE orders
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = NEW.id;
            END;
            """
        )
        ensure_orders_access_key_column(connection)
        seed_menu(connection, MENU_CSV_PATH)


def seed_menu(connection: sqlite3.Connection, csv_path: Path) -> None:
    existing_count = connection.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
    if existing_count > 0:
        return

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontro el archivo de carta: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = []
        for row in reader:
            price = parse_price(row["Precio"])
            rows.append((row["Categoria"].strip(), row["Plato"].strip(), price))

    connection.executemany(
        "INSERT OR IGNORE INTO menu_items (category, name, price) VALUES (?, ?, ?)",
        rows,
    )


def parse_price(value: str) -> int:
    cleaned = value.replace(".", "").replace(",", "").strip()
    return int(cleaned)


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def normalize_access_key(access_key: str) -> str:
    return " ".join(access_key.strip().casefold().split())


def ensure_orders_access_key_column(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()}
    if "access_key" not in columns:
        connection.execute("ALTER TABLE orders ADD COLUMN access_key TEXT")

    existing_orders = connection.execute(
        "SELECT id, order_code FROM orders WHERE access_key IS NULL OR TRIM(access_key) = ''"
    ).fetchall()
    for row in existing_orders:
        connection.execute(
            "UPDATE orders SET access_key = ? WHERE id = ?",
            (normalize_access_key(row["order_code"]), row["id"]),
        )

    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_access_key ON orders(access_key)")


def create_user(name: str, email: str | None = None) -> int:
    normalized_name = normalize_name(name)
    normalized_email = email.strip() if email else None

    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (normalized_name, normalized_email or None),
        )
        return int(cursor.lastrowid)


def get_users() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name, email, created_at FROM users ORDER BY name COLLATE NOCASE"
        ).fetchall()


def get_user_by_name(name: str) -> sqlite3.Row | None:
    normalized_name = normalize_name(name)
    if not normalized_name:
        return None

    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name, email, created_at FROM users WHERE name = ? COLLATE NOCASE",
            (normalized_name,),
        ).fetchone()


def get_or_create_user(name: str) -> int:
    normalized_name = normalize_name(name)
    if not normalized_name:
        raise ValueError("El nombre del usuario es obligatorio.")

    with get_connection() as connection:
        existing_user = connection.execute(
            "SELECT id FROM users WHERE name = ? COLLATE NOCASE",
            (normalized_name,),
        ).fetchone()
        if existing_user is not None:
            return int(existing_user["id"])

        cursor = connection.execute(
            "INSERT INTO users (name) VALUES (?)",
            (normalized_name,),
        )
        return int(cursor.lastrowid)


def get_user(user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def create_order(title: str, created_by: int, access_key: str) -> int:
    normalized_title = normalize_name(title)
    normalized_access_key = normalize_access_key(access_key)
    if not normalized_title:
        raise ValueError("El pedido necesita un nombre.")
    if not normalized_access_key:
        raise ValueError("La palabra clave del pedido es obligatoria.")

    with get_connection() as connection:
        order_code = generate_order_code(connection)
        cursor = connection.execute(
            "INSERT INTO orders (order_code, title, access_key, created_by) VALUES (?, ?, ?, ?)",
            (order_code, normalized_title, normalized_access_key, created_by),
        )
        order_id = int(cursor.lastrowid)
        connection.execute(INSERT_ORDER_MEMBER_SQL, (order_id, created_by))
        return order_id


def generate_order_code(connection: sqlite3.Connection) -> str:
    while True:
        candidate = uuid.uuid4().hex[:8].upper()
        existing = connection.execute(
            "SELECT 1 FROM orders WHERE order_code = ?",
            (candidate,),
        ).fetchone()
        if existing is None:
            return candidate


def get_orders() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                o.id,
                o.order_code,
                o.title,
                o.status,
                o.created_at,
                o.updated_at,
                creator.name AS created_by_name,
                COALESCE(order_totals.total_amount, 0) AS total_amount,
                COALESCE(member_totals.member_count, 0) AS member_count
            FROM orders o
            JOIN users creator ON creator.id = o.created_by
            LEFT JOIN (
                SELECT oi.order_id, SUM(mi.price * oi.quantity) AS total_amount
                FROM order_items oi
                JOIN menu_items mi ON mi.id = oi.menu_item_id
                GROUP BY oi.order_id
            ) AS order_totals ON order_totals.order_id = o.id
            LEFT JOIN (
                SELECT order_id, COUNT(DISTINCT user_id) AS member_count
                FROM order_members
                GROUP BY order_id
            ) AS member_totals ON member_totals.order_id = o.id
            ORDER BY CASE o.status WHEN 'open' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, o.updated_at DESC
            """
        ).fetchall()


def get_order(order_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                o.id,
                o.order_code,
                o.title,
                o.access_key,
                o.status,
                o.created_by,
                o.created_at,
                o.updated_at,
                creator.name AS created_by_name,
                COALESCE(SUM(mi.price * oi.quantity), 0) AS total_amount
            FROM orders o
            JOIN users creator ON creator.id = o.created_by
            LEFT JOIN order_items oi ON oi.order_id = o.id
            LEFT JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE o.id = ?
            GROUP BY o.id, o.order_code, o.title, o.access_key, o.status, o.created_by, o.created_at, o.updated_at, creator.name
            """,
            (order_id,),
        ).fetchone()


def get_order_by_access_key(access_key: str) -> sqlite3.Row | None:
    normalized_access_key = normalize_access_key(access_key)
    if not normalized_access_key:
        return None

    with get_connection() as connection:
        return connection.execute(
            "SELECT id, order_code, title, access_key, status, created_by, created_at, updated_at FROM orders WHERE access_key = ?",
            (normalized_access_key,),
        ).fetchone()


def join_order(order_id: int, user_id: int) -> None:
    with get_connection() as connection:
        connection.execute(INSERT_ORDER_MEMBER_SQL, (order_id, user_id))


def ensure_user_owns_order(connection: sqlite3.Connection, order_id: int, user_id: int) -> sqlite3.Row:
    order = connection.execute(
        "SELECT id, status, created_by FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        raise ValueError("El pedido ya no existe.")
    if int(order["created_by"]) != int(user_id):
        raise PermissionError("Solo quien creó el pedido puede hacer esta acción.")
    return order


def ensure_order_allows_changes(connection: sqlite3.Connection, order_id: int) -> None:
    order = connection.execute(
        "SELECT status FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        raise ValueError("El pedido ya no existe.")
    if order["status"] == "closed":
        raise ValueError("El pedido está cerrado y ya no admite cambios.")


def update_order_status(order_id: int, status: str, requested_by: int) -> None:
    normalized_status = status.strip().lower()
    if normalized_status not in ALLOWED_ORDER_STATUSES:
        raise ValueError("Estado de pedido inválido.")

    with get_connection() as connection:
        ensure_user_owns_order(connection, order_id, requested_by)
        connection.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (normalized_status, order_id),
        )


def delete_order(order_id: int, requested_by: int) -> None:
    with get_connection() as connection:
        ensure_user_owns_order(connection, order_id, requested_by)
        connection.execute("DELETE FROM orders WHERE id = ?", (order_id,))


def get_order_members(order_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT u.id, u.name, u.email, om.joined_at
            FROM order_members om
            JOIN users u ON u.id = om.user_id
            WHERE om.order_id = ?
            ORDER BY u.name COLLATE NOCASE
            """,
            (order_id,),
        ).fetchall()


def get_menu_items() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, category, name, price FROM menu_items ORDER BY category COLLATE NOCASE, name COLLATE NOCASE"
        ).fetchall()


def get_menu_by_category() -> dict[str, list[sqlite3.Row]]:
    items_by_category: dict[str, list[sqlite3.Row]] = {}
    for row in get_menu_items():
        items_by_category.setdefault(row["category"], []).append(row)
    return items_by_category


def add_order_item(order_id: int, user_id: int, menu_item_id: int, quantity: int, notes: str | None = None) -> None:
    with get_connection() as connection:
        ensure_order_allows_changes(connection, order_id)
        connection.execute(INSERT_ORDER_MEMBER_SQL, (order_id, user_id))
        connection.execute(
            """
            INSERT INTO order_items (order_id, user_id, menu_item_id, quantity, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, user_id, menu_item_id, quantity, notes.strip() if notes else None),
        )
        connection.execute("UPDATE orders SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,))


def remove_order_item(order_item_id: int) -> None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT order_id FROM order_items WHERE id = ?",
            (order_item_id,),
        ).fetchone()
        if row is None:
            return

        ensure_order_allows_changes(connection, row["order_id"])
        connection.execute("DELETE FROM order_items WHERE id = ?", (order_item_id,))
        connection.execute("UPDATE orders SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["order_id"],))


def get_order_items(order_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                oi.id,
                oi.order_id,
                oi.user_id,
                oi.menu_item_id,
                oi.quantity,
                oi.notes,
                oi.created_at,
                u.name AS user_name,
                mi.category,
                mi.name AS item_name,
                mi.price,
                mi.price * oi.quantity AS subtotal
            FROM order_items oi
            JOIN users u ON u.id = oi.user_id
            JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE oi.order_id = ?
            ORDER BY u.name COLLATE NOCASE, oi.created_at DESC, oi.id DESC
            """,
            (order_id,),
        ).fetchall()


def get_order_totals_by_user(order_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                u.id AS user_id,
                u.name AS user_name,
                COALESCE(SUM(mi.price * oi.quantity), 0) AS total_amount,
                COALESCE(SUM(oi.quantity), 0) AS total_items
            FROM order_members om
            JOIN users u ON u.id = om.user_id
            LEFT JOIN order_items oi ON oi.order_id = om.order_id AND oi.user_id = om.user_id
            LEFT JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE om.order_id = ?
            GROUP BY u.id, u.name
            ORDER BY u.name COLLATE NOCASE
            """,
            (order_id,),
        ).fetchall()


def format_currency(amount: int | float) -> str:
    return f"$ {amount:,.0f}".replace(",", ".")


def as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}