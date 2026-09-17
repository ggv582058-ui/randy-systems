from __future__ import annotations

import sqlite3
import hashlib
import hmac
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StoreError(Exception):
    pass


class NotApproved(StoreError):
    pass


class InsufficientBalance(StoreError):
    pass


class OutOfStock(StoreError):
    pass


class NotFound(StoreError):
    pass


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'pending'
                        CHECK(role IN ('pending','reseller','admin','rejected')),
                    balance_cents INTEGER NOT NULL DEFAULT 0 CHECK(balance_cents >= 0),
                    requested_access INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    secret_value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','sold')),
                    sold_to INTEGER REFERENCES users(telegram_id),
                    sold_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(product_id, secret_value)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    inventory_key_id INTEGER NOT NULL UNIQUE REFERENCES inventory_keys(id),
                    amount_cents INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS topups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    proof_type TEXT NOT NULL,
                    proof_value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','approved','rejected')),
                    reviewed_by INTEGER REFERENCES users(telegram_id),
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    kind TEXT NOT NULL CHECK(kind IN ('topup','purchase','adjustment')),
                    amount_cents INTEGER NOT NULL,
                    balance_after_cents INTEGER NOT NULL,
                    reference TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_inventory_available
                    ON inventory_keys(product_id, status);
                CREATE INDEX IF NOT EXISTS idx_topups_status ON topups(status);
                CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id DESC);

                CREATE TABLE IF NOT EXISTS partner_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    telegram_id INTEGER UNIQUE REFERENCES users(telegram_id),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_files (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL
                );
                """
            )

    def create_partner(self, login: str, password: str) -> None:
        login = login.strip()
        if len(login) < 3 or len(password) < 6:
            raise ValueError("Usuario mínimo 3 caracteres y contraseña mínimo 6")
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
        with self.transaction() as con:
            con.execute(
                "INSERT INTO partner_accounts(login,password_hash,password_salt,created_at) VALUES(?,?,?,?)",
                (login, digest.hex(), salt.hex(), utcnow()),
            )

    def activate_partner(self, login: str, password: str, telegram_id: int) -> bool:
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM partner_accounts WHERE login=? COLLATE NOCASE AND active=1", (login.strip(),)
            ).fetchone()
            if not row or row["telegram_id"] not in (None, telegram_id):
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(row["password_salt"]), 210_000)
            if not hmac.compare_digest(digest.hex(), row["password_hash"]):
                return False
            con.execute("UPDATE partner_accounts SET telegram_id=? WHERE id=?", (telegram_id, row["id"]))
            con.execute("UPDATE users SET role='reseller', requested_access=0, updated_at=? WHERE telegram_id=?", (utcnow(), telegram_id))
            return True

    def set_product_file(self, product_id: int, file_id: str, file_name: str) -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO product_files(product_id,file_id,file_name,uploaded_at) VALUES(?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET file_id=excluded.file_id,file_name=excluded.file_name,uploaded_at=excluded.uploaded_at""",
                (product_id, file_id, file_name, utcnow()),
            )

    def reseller_ids(self) -> list[int]:
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT telegram_id FROM users WHERE role='reseller'").fetchall()]

    def ensure_user(self, telegram_id: int, username: str | None, full_name: str, is_admin: bool) -> sqlite3.Row:
        now = utcnow()
        role = "admin" if is_admin else "pending"
        with self.transaction() as con:
            con.execute(
                """INSERT INTO users(telegram_id, username, full_name, role, created_at, updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(telegram_id) DO UPDATE SET
                     username=excluded.username, full_name=excluded.full_name,
                     role=CASE WHEN ? THEN 'admin' ELSE users.role END,
                     updated_at=excluded.updated_at""",
                (telegram_id, username, full_name, role, now, now, int(is_admin)),
            )
            return con.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()

    def user(self, telegram_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()

    def request_access(self, telegram_id: int) -> bool:
        with self.transaction() as con:
            row = con.execute("SELECT role, requested_access FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            if not row or row["role"] in ("reseller", "admin"):
                return False
            first = not bool(row["requested_access"])
            con.execute(
                "UPDATE users SET role='pending', requested_access=1, updated_at=? WHERE telegram_id=?",
                (utcnow(), telegram_id),
            )
            return first

    def set_role(self, telegram_id: int, role: str) -> bool:
        if role not in {"pending", "reseller", "admin", "rejected"}:
            raise ValueError("Rol inválido")
        with self.transaction() as con:
            cur = con.execute(
                "UPDATE users SET role=?, requested_access=0, updated_at=? WHERE telegram_id=?",
                (role, utcnow(), telegram_id),
            )
            return cur.rowcount == 1

    def pending_users(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM users WHERE role='pending' AND requested_access=1 ORDER BY created_at"
            ).fetchall()

    def approved_users(self, limit: int = 30) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM users WHERE role='reseller' ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def create_product(self, name: str, price_cents: int, description: str = "") -> int:
        with self.transaction() as con:
            cur = con.execute(
                "INSERT INTO products(name, description, price_cents, created_at) VALUES(?,?,?,?)",
                (name.strip(), description.strip(), price_cents, utcnow()),
            )
            return int(cur.lastrowid)

    def product(self, product_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """SELECT p.*, COUNT(CASE WHEN k.status='available' THEN 1 END) AS stock
                   FROM products p LEFT JOIN inventory_keys k ON k.product_id=p.id
                   WHERE p.id=? GROUP BY p.id""",
                (product_id,),
            ).fetchone()

    def products(self, active_only: bool = True) -> list[sqlite3.Row]:
        where = "WHERE p.active=1" if active_only else ""
        with self.connect() as con:
            return con.execute(
                f"""SELECT p.*, COUNT(CASE WHEN k.status='available' THEN 1 END) AS stock
                    FROM products p LEFT JOIN inventory_keys k ON k.product_id=p.id
                    {where} GROUP BY p.id ORDER BY p.id DESC"""
            ).fetchall()

    def set_product_active(self, product_id: int, active: bool) -> bool:
        with self.transaction() as con:
            cur = con.execute("UPDATE products SET active=? WHERE id=?", (int(active), product_id))
            return cur.rowcount == 1

    def add_keys(self, product_id: int, values: Iterable[str]) -> tuple[int, int]:
        clean = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        added = 0
        with self.transaction() as con:
            if not con.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
                raise NotFound("Producto no encontrado")
            for value in clean:
                cur = con.execute(
                    "INSERT OR IGNORE INTO inventory_keys(product_id, secret_value, created_at) VALUES(?,?,?)",
                    (product_id, value, utcnow()),
                )
                added += cur.rowcount
        return added, len(clean) - added

    def create_topup(self, user_id: int, amount_cents: int, proof_type: str, proof_value: str) -> int:
        with self.transaction() as con:
            row = con.execute("SELECT role FROM users WHERE telegram_id=?", (user_id,)).fetchone()
            if not row or row["role"] not in ("reseller", "admin"):
                raise NotApproved("Usuario no aprobado")
            cur = con.execute(
                "INSERT INTO topups(user_id, amount_cents, proof_type, proof_value, created_at) VALUES(?,?,?,?,?)",
                (user_id, amount_cents, proof_type, proof_value, utcnow()),
            )
            return int(cur.lastrowid)

    def pending_topups(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT t.*, u.username, u.full_name FROM topups t
                   JOIN users u ON u.telegram_id=t.user_id
                   WHERE t.status='pending' ORDER BY t.id LIMIT ?""",
                (limit,),
            ).fetchall()

    def topup(self, topup_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """SELECT t.*, u.username, u.full_name FROM topups t
                   JOIN users u ON u.telegram_id=t.user_id WHERE t.id=?""",
                (topup_id,),
            ).fetchone()

    def approve_topup(self, topup_id: int, admin_id: int) -> tuple[bool, sqlite3.Row | None]:
        with self.transaction() as con:
            topup = con.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()
            if not topup or topup["status"] != "pending":
                return False, topup
            con.execute(
                "UPDATE users SET balance_cents=balance_cents+?, updated_at=? WHERE telegram_id=?",
                (topup["amount_cents"], utcnow(), topup["user_id"]),
            )
            balance = con.execute(
                "SELECT balance_cents FROM users WHERE telegram_id=?", (topup["user_id"],)
            ).fetchone()["balance_cents"]
            con.execute(
                "UPDATE topups SET status='approved', reviewed_by=?, reviewed_at=? WHERE id=?",
                (admin_id, utcnow(), topup_id),
            )
            con.execute(
                "INSERT INTO ledger(user_id, kind, amount_cents, balance_after_cents, reference, created_at) VALUES(?,?,?,?,?,?)",
                (topup["user_id"], "topup", topup["amount_cents"], balance, f"topup:{topup_id}", utcnow()),
            )
            return True, con.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()

    def reject_topup(self, topup_id: int, admin_id: int) -> tuple[bool, sqlite3.Row | None]:
        with self.transaction() as con:
            topup = con.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()
            if not topup or topup["status"] != "pending":
                return False, topup
            con.execute(
                "UPDATE topups SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
                (admin_id, utcnow(), topup_id),
            )
            return True, topup

    def purchase(self, user_id: int, product_id: int) -> dict:
        with self.transaction() as con:
            user = con.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,)).fetchone()
            if not user or user["role"] not in ("reseller", "admin"):
                raise NotApproved("Tu cuenta no está aprobada")
            product = con.execute(
                "SELECT * FROM products WHERE id=? AND active=1", (product_id,)
            ).fetchone()
            if not product:
                raise NotFound("Producto no disponible")
            key = con.execute(
                "SELECT * FROM inventory_keys WHERE product_id=? AND status='available' ORDER BY id LIMIT 1",
                (product_id,),
            ).fetchone()
            if not key:
                raise OutOfStock("Producto sin stock")
            if user["balance_cents"] < product["price_cents"]:
                raise InsufficientBalance("Saldo insuficiente")

            now = utcnow()
            claimed = con.execute(
                "UPDATE inventory_keys SET status='sold', sold_to=?, sold_at=? WHERE id=? AND status='available'",
                (user_id, now, key["id"]),
            )
            if claimed.rowcount != 1:
                raise OutOfStock("La key fue tomada; intenta nuevamente")
            balance = user["balance_cents"] - product["price_cents"]
            con.execute(
                "UPDATE users SET balance_cents=?, updated_at=? WHERE telegram_id=?",
                (balance, now, user_id),
            )
            cur = con.execute(
                "INSERT INTO orders(user_id, product_id, inventory_key_id, amount_cents, created_at) VALUES(?,?,?,?,?)",
                (user_id, product_id, key["id"], product["price_cents"], now),
            )
            order_id = int(cur.lastrowid)
            con.execute(
                "INSERT INTO ledger(user_id, kind, amount_cents, balance_after_cents, reference, created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "purchase", -product["price_cents"], balance, f"order:{order_id}", now),
            )
            return {
                "order_id": order_id,
                "product_name": product["name"],
                "key": key["secret_value"],
                "price_cents": product["price_cents"],
                "balance_cents": balance,
                "file": con.execute("SELECT file_id,file_name FROM product_files WHERE product_id=?", (product_id,)).fetchone(),
            }

    def history(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()

    def stats(self) -> dict[str, int]:
        with self.connect() as con:
            return {
                "resellers": con.execute("SELECT COUNT(*) FROM users WHERE role='reseller'").fetchone()[0],
                "pending_users": con.execute("SELECT COUNT(*) FROM users WHERE role='pending' AND requested_access=1").fetchone()[0],
                "available_keys": con.execute("SELECT COUNT(*) FROM inventory_keys WHERE status='available'").fetchone()[0],
                "orders": con.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                "revenue_cents": con.execute("SELECT COALESCE(SUM(amount_cents),0) FROM orders").fetchone()[0],
                "pending_topups": con.execute("SELECT COUNT(*) FROM topups WHERE status='pending'").fetchone()[0],
            }
