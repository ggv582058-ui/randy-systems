from __future__ import annotations

import sqlite3
import hashlib
import hmac
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


class ProductRestricted(StoreError):
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

    def backup(self, keep: int = 10) -> Path | None:
        """Create a consistent on-disk backup before startup migrations."""
        source_path = Path(self.path)
        if not source_path.exists() or source_path.stat().st_size == 0:
            return None
        backup_dir = source_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{source_path.stem}-{stamp}.db"
        source = sqlite3.connect(self.path, timeout=30)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        backups = sorted(backup_dir.glob(f"{source_path.stem}-*.db"), reverse=True)
        for old in backups[max(1, keep):]:
            old.unlink(missing_ok=True)
        return backup_path

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
        self.backup()
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
                    tier TEXT NOT NULL DEFAULT 'regular'
                        CHECK(tier IN ('regular','vip')),
                    language TEXT NOT NULL DEFAULT 'es'
                        CHECK(language IN ('es','en')),
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
                    initial_balance_cents INTEGER NOT NULL DEFAULT 0,
                    target_role TEXT NOT NULL DEFAULT 'reseller',
                    target_tier TEXT NOT NULL DEFAULT 'regular',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_files (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_data BLOB,
                    uploaded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reseller_prices (
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, product_id)
                );

                CREATE TABLE IF NOT EXISTS reseller_product_access (
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    allowed INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, product_id)
                );

                CREATE TABLE IF NOT EXISTS product_media (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    photo_data BLOB,
                    photo_name TEXT,
                    sticker_data BLOB,
                    sticker_name TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS certificate_offer_media (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    photo_data BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS certificate_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','processing','used','refunded')),
                    created_at TEXT NOT NULL,
                    redeemed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS certificate_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    certificate_key_id INTEGER NOT NULL UNIQUE REFERENCES certificate_keys(id),
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    plan_id INTEGER NOT NULL,
                    udid TEXT NOT NULL,
                    device TEXT NOT NULL CHECK(device IN ('iphone','ipad')),
                    p12_password TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'submitting',
                    provider_order_code TEXT UNIQUE,
                    provider_amount_cents INTEGER,
                    download_url TEXT,
                    install_token TEXT NOT NULL UNIQUE,
                    install_expires_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    delivered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS private_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_announcements (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    body TEXT NOT NULL,
                    send_time TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_sent_date TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_certificate_orders_user
                    ON certificate_orders(user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_certificate_orders_status
                    ON certificate_orders(status, updated_at);
                """
            )

            # Migraciones seguras para instalaciones creadas con versiones anteriores.
            product_file_columns = {row["name"] for row in con.execute("PRAGMA table_info(product_files)")}
            if "file_data" not in product_file_columns:
                con.execute("ALTER TABLE product_files ADD COLUMN file_data BLOB")
            topup_columns = {row["name"] for row in con.execute("PRAGMA table_info(topups)")}
            if "proof_blob" not in topup_columns:
                con.execute("ALTER TABLE topups ADD COLUMN proof_blob BLOB")
            if "proof_name" not in topup_columns:
                con.execute("ALTER TABLE topups ADD COLUMN proof_name TEXT")

            product_columns = {row["name"] for row in con.execute("PRAGMA table_info(products)")}
            if "duration_days" not in product_columns:
                con.execute("ALTER TABLE products ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 30")
            if "instructions" not in product_columns:
                con.execute("ALTER TABLE products ADD COLUMN instructions TEXT NOT NULL DEFAULT ''")
            if "name_html" not in product_columns:
                con.execute("ALTER TABLE products ADD COLUMN name_html TEXT NOT NULL DEFAULT ''")
            if "custom_emoji_id" not in product_columns:
                con.execute("ALTER TABLE products ADD COLUMN custom_emoji_id TEXT NOT NULL DEFAULT ''")

            order_columns = {row["name"] for row in con.execute("PRAGMA table_info(orders)")}
            if "duration_days" not in order_columns:
                con.execute("ALTER TABLE orders ADD COLUMN duration_days INTEGER")
            if "expires_at" not in order_columns:
                con.execute("ALTER TABLE orders ADD COLUMN expires_at TEXT")

            partner_columns = {row["name"] for row in con.execute("PRAGMA table_info(partner_accounts)")}
            if "initial_balance_cents" not in partner_columns:
                con.execute("ALTER TABLE partner_accounts ADD COLUMN initial_balance_cents INTEGER NOT NULL DEFAULT 0")
            if "target_role" not in partner_columns:
                con.execute("ALTER TABLE partner_accounts ADD COLUMN target_role TEXT NOT NULL DEFAULT 'reseller'")
            if "target_tier" not in partner_columns:
                con.execute("ALTER TABLE partner_accounts ADD COLUMN target_tier TEXT NOT NULL DEFAULT 'regular'")

            user_columns = {row["name"] for row in con.execute("PRAGMA table_info(users)")}
            if "tier" not in user_columns:
                con.execute("ALTER TABLE users ADD COLUMN tier TEXT NOT NULL DEFAULT 'regular'")
            if "language" not in user_columns:
                con.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'es'")

    def create_partner(self, login: str, password: str, initial_balance_cents: int = 0,
                       target_role: str = "reseller", target_tier: str = "regular") -> None:
        login = login.strip()
        if len(login) < 3 or len(password) < 6:
            raise ValueError("Usuario mínimo 3 caracteres y contraseña mínimo 6")
        if target_role not in {"reseller", "admin"}:
            raise ValueError("Rol inválido")
        if target_tier not in {"regular", "vip"}:
            raise ValueError("Rango inválido")
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
        with self.transaction() as con:
            con.execute(
                """INSERT INTO partner_accounts(login,password_hash,password_salt,initial_balance_cents,
                   target_role,target_tier,created_at) VALUES(?,?,?,?,?,?,?)""",
                (login, digest.hex(), salt.hex(), initial_balance_cents, target_role, target_tier, utcnow()),
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
            newly_bound = row["telegram_id"] is None
            con.execute("UPDATE partner_accounts SET telegram_id=? WHERE id=?", (telegram_id, row["id"]))
            if newly_bound:
                con.execute(
                    """UPDATE users SET role=?,tier=?,requested_access=0,
                       balance_cents=balance_cents+?,updated_at=? WHERE telegram_id=?""",
                    (row["target_role"], row["target_tier"], row["initial_balance_cents"], utcnow(), telegram_id),
                )
                if row["initial_balance_cents"]:
                    balance = con.execute("SELECT balance_cents FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()[0]
                    con.execute(
                        """INSERT INTO ledger(user_id,kind,amount_cents,balance_after_cents,reference,created_at)
                           VALUES(?,?,?,?,?,?)""",
                        (telegram_id, "adjustment", row["initial_balance_cents"], balance, "initial-balance", utcnow()),
                    )
            else:
                con.execute(
                    "UPDATE users SET role=?,tier=?,requested_access=0,updated_at=? WHERE telegram_id=?",
                    (row["target_role"], row["target_tier"], utcnow(), telegram_id),
                )
            return True

    def set_product_file(self, product_id: int, file_id: str, file_name: str, file_data: bytes) -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO product_files(product_id,file_id,file_name,file_data,uploaded_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET file_id=excluded.file_id,file_name=excluded.file_name,
                   file_data=excluded.file_data,uploaded_at=excluded.uploaded_at""",
                (product_id, file_id, file_name, file_data, utcnow()),
            )

    def set_product_photo(self, product_id: int, data: bytes, name: str = "product.jpg") -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO product_media(product_id,photo_data,photo_name,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET photo_data=excluded.photo_data,
                   photo_name=excluded.photo_name,updated_at=excluded.updated_at""",
                (product_id, data, name, utcnow()),
            )

    def set_product_sticker(self, product_id: int, data: bytes, name: str) -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO product_media(product_id,sticker_data,sticker_name,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET sticker_data=excluded.sticker_data,
                   sticker_name=excluded.sticker_name,updated_at=excluded.updated_at""",
                (product_id, data, name, utcnow()),
            )

    def product_media(self, product_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM product_media WHERE product_id=?", (product_id,)).fetchone()

    def set_certificate_offer_photo(self, data: bytes) -> None:
        with self.transaction() as con:
            con.execute("""INSERT INTO certificate_offer_media(id,photo_data,updated_at) VALUES(1,?,?)
                           ON CONFLICT(id) DO UPDATE SET photo_data=excluded.photo_data,
                           updated_at=excluded.updated_at""", (data, utcnow()))

    def certificate_offer_photo(self) -> bytes | None:
        with self.connect() as con:
            row = con.execute("SELECT photo_data FROM certificate_offer_media WHERE id=1").fetchone()
            return row["photo_data"] if row else None

    def reseller_ids(self) -> list[int]:
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT telegram_id FROM users WHERE role='reseller'").fetchall()]

    def admin_ids(self) -> list[int]:
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT telegram_id FROM users WHERE role='admin'").fetchall()]

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

    def set_language(self, telegram_id: int, language: str) -> bool:
        if language not in {"es", "en"}:
            raise ValueError("Idioma inválido")
        with self.transaction() as con:
            cur = con.execute(
                "UPDATE users SET language=?,updated_at=? WHERE telegram_id=?",
                (language, utcnow(), telegram_id),
            )
            return cur.rowcount == 1

    def set_tier(self, telegram_id: int, tier: str) -> bool:
        if tier not in {"regular", "vip"}:
            raise ValueError("Rango inválido")
        with self.transaction() as con:
            cur = con.execute(
                "UPDATE users SET tier=?,updated_at=? WHERE telegram_id=? AND role='reseller'",
                (tier, utcnow(), telegram_id),
            )
            return cur.rowcount == 1

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

    def reseller(self, telegram_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """SELECT u.*, p.login FROM users u
                   LEFT JOIN partner_accounts p ON p.telegram_id=u.telegram_id
                   WHERE u.telegram_id=? AND u.role='reseller'""",
                (telegram_id,),
            ).fetchone()

    def adjust_balance(self, user_id: int, amount_cents: int, admin_id: int) -> int:
        if amount_cents == 0:
            raise ValueError("La cantidad no puede ser cero")
        with self.transaction() as con:
            row = con.execute("SELECT balance_cents, role FROM users WHERE telegram_id=?", (user_id,)).fetchone()
            if not row or row["role"] != "reseller":
                raise NotFound("Socio no encontrado")
            balance = row["balance_cents"] + amount_cents
            if balance < 0:
                raise InsufficientBalance("El socio no tiene saldo suficiente")
            now = utcnow()
            con.execute("UPDATE users SET balance_cents=?, updated_at=? WHERE telegram_id=?", (balance, now, user_id))
            con.execute(
                "INSERT INTO ledger(user_id,kind,amount_cents,balance_after_cents,reference,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "adjustment", amount_cents, balance, f"admin:{admin_id}", now),
            )
            return balance

    def set_reseller_price(self, user_id: int, product_id: int, price_cents: int) -> None:
        with self.transaction() as con:
            if not con.execute("SELECT 1 FROM users WHERE telegram_id=? AND role='reseller'", (user_id,)).fetchone():
                raise NotFound("Socio no encontrado")
            if not con.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
                raise NotFound("Producto no encontrado")
            con.execute(
                """INSERT INTO reseller_prices(user_id,product_id,price_cents,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(user_id,product_id) DO UPDATE SET price_cents=excluded.price_cents,updated_at=excluded.updated_at""",
                (user_id, product_id, price_cents, utcnow()),
            )

    def reseller_prices(self, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT p.id,p.name,p.price_cents AS regular_price_cents,rp.price_cents AS reseller_price_cents
                   FROM products p LEFT JOIN reseller_prices rp ON rp.product_id=p.id AND rp.user_id=?
                   ORDER BY p.id DESC""",
                (user_id,),
            ).fetchall()

    def create_product(self, name: str, price_cents: int, description: str = "", duration_days: int = 30,
                       instructions: str = "", name_html: str = "", custom_emoji_id: str = "") -> int:
        if duration_days < 1 or duration_days > 3650:
            raise ValueError("Duración inválida")
        with self.transaction() as con:
            cur = con.execute(
                """INSERT INTO products(name,description,price_cents,duration_days,instructions,name_html,custom_emoji_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (name.strip(), description.strip(), price_cents, duration_days, instructions.strip(),
                 name_html, custom_emoji_id, utcnow()),
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

    def update_product(self, product_id: int, field: str, value: str | int) -> bool:
        allowed = {"name", "description", "price_cents", "duration_days", "instructions"}
        if field not in allowed:
            raise ValueError("Campo de producto inválido")
        if field == "price_cents" and (not isinstance(value, int) or value <= 0):
            raise ValueError("Precio inválido")
        if field == "duration_days" and (not isinstance(value, int) or not 1 <= value <= 3650):
            raise ValueError("Duración inválida")
        with self.transaction() as con:
            cur = con.execute(f"UPDATE products SET {field}=? WHERE id=?", (value, product_id))
            return cur.rowcount == 1

    def update_product_name(self, product_id: int, name: str, name_html: str, custom_emoji_id: str) -> bool:
        with self.transaction() as con:
            cur = con.execute("UPDATE products SET name=?,name_html=?,custom_emoji_id=? WHERE id=?",
                              (name, name_html, custom_emoji_id, product_id))
            return cur.rowcount == 1

    def daily_announcement(self) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute("SELECT * FROM daily_announcements WHERE id=1").fetchone()

    def set_daily_announcement(self, body: str, send_time: str, last_sent_date: str | None = None) -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO daily_announcements(id,body,send_time,enabled,last_sent_date,updated_at)
                   VALUES(1,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET
                   body=excluded.body,send_time=excluded.send_time,enabled=1,
                   last_sent_date=excluded.last_sent_date,updated_at=excluded.updated_at""",
                (body, send_time, last_sent_date, utcnow()),
            )

    def pause_daily_announcement(self) -> None:
        with self.transaction() as con:
            con.execute("UPDATE daily_announcements SET enabled=0,updated_at=? WHERE id=1", (utcnow(),))

    def claim_daily_announcement(self, local_date: str, local_time: str) -> str | None:
        with self.transaction() as con:
            row = con.execute("SELECT body FROM daily_announcements WHERE id=1 AND enabled=1 "
                              "AND send_time<=? AND (last_sent_date IS NULL OR last_sent_date<>?)",
                              (local_time, local_date)).fetchone()
            if row:
                con.execute("UPDATE daily_announcements SET last_sent_date=? WHERE id=1", (local_date,))
                return row["body"]
        return None

    def products(self, active_only: bool = True) -> list[sqlite3.Row]:
        where = "WHERE p.active=1" if active_only else ""
        with self.connect() as con:
            return con.execute(
                f"""SELECT p.*, COUNT(CASE WHEN k.status='available' THEN 1 END) AS stock
                    FROM products p LEFT JOIN inventory_keys k ON k.product_id=p.id
                    {where} GROUP BY p.id ORDER BY p.id DESC"""
            ).fetchall()

    def products_for_user(self, user_id: int, active_only: bool = True) -> list[sqlite3.Row]:
        where = "WHERE p.active=1 AND COALESCE(a.allowed,1)=1" if active_only else "WHERE COALESCE(a.allowed,1)=1"
        with self.connect() as con:
            return con.execute(
                f"""SELECT p.*, COALESCE(rp.price_cents,p.price_cents) AS effective_price_cents,
                    COUNT(CASE WHEN k.status='available' THEN 1 END) AS stock
                    FROM products p
                    LEFT JOIN reseller_prices rp ON rp.product_id=p.id AND rp.user_id=?
                    LEFT JOIN reseller_product_access a ON a.product_id=p.id AND a.user_id=?
                    LEFT JOIN inventory_keys k ON k.product_id=p.id
                    {where} GROUP BY p.id ORDER BY p.id DESC""",
                (user_id, user_id),
            ).fetchall()

    def product_for_user(self, product_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """SELECT p.*, COALESCE(rp.price_cents,p.price_cents) AS effective_price_cents,
                   COALESCE(a.allowed,1) AS allowed,
                   COUNT(CASE WHEN k.status='available' THEN 1 END) AS stock
                   FROM products p
                   LEFT JOIN reseller_prices rp ON rp.product_id=p.id AND rp.user_id=?
                   LEFT JOIN reseller_product_access a ON a.product_id=p.id AND a.user_id=?
                   LEFT JOIN inventory_keys k ON k.product_id=p.id
                   WHERE p.id=? GROUP BY p.id""",
                (user_id, user_id, product_id),
            ).fetchone()

    def product_access(self, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT p.id,p.name,COALESCE(a.allowed,1) AS allowed
                   FROM products p LEFT JOIN reseller_product_access a
                   ON a.product_id=p.id AND a.user_id=? ORDER BY p.id DESC""",
                (user_id,),
            ).fetchall()

    def toggle_product_access(self, user_id: int, product_id: int) -> bool:
        with self.transaction() as con:
            current = con.execute(
                "SELECT allowed FROM reseller_product_access WHERE user_id=? AND product_id=?",
                (user_id, product_id),
            ).fetchone()
            allowed = not bool(current["allowed"]) if current else False
            con.execute(
                """INSERT INTO reseller_product_access(user_id,product_id,allowed,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(user_id,product_id) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at""",
                (user_id, product_id, int(allowed), utcnow()),
            )
            return allowed

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

    def create_topup(self, user_id: int, amount_cents: int, proof_type: str, proof_value: str,
                     proof_blob: bytes | None = None, proof_name: str | None = None) -> int:
        with self.transaction() as con:
            row = con.execute("SELECT role FROM users WHERE telegram_id=?", (user_id,)).fetchone()
            if not row or row["role"] not in ("reseller", "admin"):
                raise NotApproved("Usuario no aprobado")
            cur = con.execute(
                """INSERT INTO topups(user_id,amount_cents,proof_type,proof_value,created_at,proof_blob,proof_name)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, amount_cents, proof_type, proof_value, utcnow(), proof_blob, proof_name),
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
            access = con.execute(
                "SELECT allowed FROM reseller_product_access WHERE user_id=? AND product_id=?",
                (user_id, product_id),
            ).fetchone()
            if access and not access["allowed"]:
                raise ProductRestricted("Este producto no está habilitado para tu cuenta")
            key = con.execute(
                "SELECT * FROM inventory_keys WHERE product_id=? AND status='available' ORDER BY id LIMIT 1",
                (product_id,),
            ).fetchone()
            if not key:
                raise OutOfStock("Producto sin stock")
            price = con.execute(
                "SELECT price_cents FROM reseller_prices WHERE user_id=? AND product_id=?",
                (user_id, product_id),
            ).fetchone()
            price_cents = price["price_cents"] if price else product["price_cents"]
            if user["balance_cents"] < price_cents:
                raise InsufficientBalance("Saldo insuficiente")

            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat(timespec="seconds")
            duration_days = int(product["duration_days"])
            expires_at = (now_dt + timedelta(days=duration_days)).isoformat(timespec="seconds")
            claimed = con.execute(
                "UPDATE inventory_keys SET status='sold', sold_to=?, sold_at=? WHERE id=? AND status='available'",
                (user_id, now, key["id"]),
            )
            if claimed.rowcount != 1:
                raise OutOfStock("La key fue tomada; intenta nuevamente")
            balance = user["balance_cents"] - price_cents
            con.execute(
                "UPDATE users SET balance_cents=?, updated_at=? WHERE telegram_id=?",
                (balance, now, user_id),
            )
            cur = con.execute(
                """INSERT INTO orders(user_id,product_id,inventory_key_id,amount_cents,created_at,duration_days,expires_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, product_id, key["id"], price_cents, now, duration_days, expires_at),
            )
            order_id = int(cur.lastrowid)
            con.execute(
                "INSERT INTO ledger(user_id, kind, amount_cents, balance_after_cents, reference, created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "purchase", -price_cents, balance, f"order:{order_id}", now),
            )
            return {
                "order_id": order_id,
                "product_name": product["name"],
                "key": key["secret_value"],
                "price_cents": price_cents,
                "balance_cents": balance,
                "duration_days": duration_days,
                "expires_at": expires_at,
                "instructions": product["instructions"],
                "file": con.execute("SELECT file_id,file_name,file_data FROM product_files WHERE product_id=?", (product_id,)).fetchone(),
                "media": con.execute("SELECT * FROM product_media WHERE product_id=?", (product_id,)).fetchone(),
            }

    def user_keys(self, user_id: int, limit: int = 25) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT o.id,o.created_at,o.duration_days,o.expires_at,p.name,
                   k.secret_value
                   FROM orders o JOIN products p ON p.id=o.product_id
                   JOIN inventory_keys k ON k.id=o.inventory_key_id
                   WHERE o.user_id=? ORDER BY o.id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()

    def user_key(self, user_id: int, secret_value: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """SELECT o.id,o.created_at,o.duration_days,o.expires_at,p.name,k.secret_value
                   FROM orders o JOIN products p ON p.id=o.product_id
                   JOIN inventory_keys k ON k.id=o.inventory_key_id
                   WHERE o.user_id=? AND k.secret_value=? COLLATE NOCASE
                   ORDER BY o.id DESC LIMIT 1""",
                (user_id, secret_value.strip()),
            ).fetchone()

    def history(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()

    def buy_certificate_key(self, user_id: int, key_code: str, price_cents: int) -> dict:
        """Charge the internal wallet and issue a single-use certificate key."""
        with self.transaction() as con:
            user = con.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,)).fetchone()
            if not user or user["role"] not in ("reseller", "admin"):
                raise NotApproved("Tu cuenta no está aprobada")
            if user["balance_cents"] < price_cents:
                raise InsufficientBalance("Saldo insuficiente")
            now = utcnow()
            balance = user["balance_cents"] - price_cents
            con.execute(
                "UPDATE users SET balance_cents=?,updated_at=? WHERE telegram_id=?",
                (balance, now, user_id),
            )
            cur = con.execute(
                "INSERT INTO certificate_keys(key_code,user_id,price_cents,created_at) VALUES(?,?,?,?)",
                (key_code, user_id, price_cents, now),
            )
            key_id = int(cur.lastrowid)
            con.execute(
                "INSERT INTO ledger(user_id,kind,amount_cents,balance_after_cents,reference,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "purchase", -price_cents, balance, f"certificate-key:{key_id}", now),
            )
            return {"id": key_id, "key_code": key_code, "balance_cents": balance, "price_cents": price_cents}

    def certificate_key(self, user_id: int, key_code: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM certificate_keys WHERE user_id=? AND key_code=? COLLATE NOCASE",
                (user_id, key_code.strip()),
            ).fetchone()

    def create_certificate_order(
        self, user_id: int, key_code: str, plan_id: int, udid: str, device: str,
        p12_password: str, display_name: str, install_token: str, install_expires_at: str,
    ) -> sqlite3.Row:
        with self.transaction() as con:
            key = con.execute(
                "SELECT * FROM certificate_keys WHERE user_id=? AND key_code=? COLLATE NOCASE",
                (user_id, key_code.strip()),
            ).fetchone()
            if not key:
                raise NotFound("Key de certificado no encontrada")
            if key["status"] != "available":
                raise StoreError("Esta key ya fue usada o está procesándose")
            now = utcnow()
            claimed = con.execute(
                "UPDATE certificate_keys SET status='processing',redeemed_at=? WHERE id=? AND status='available'",
                (now, key["id"]),
            )
            if claimed.rowcount != 1:
                raise StoreError("Esta key ya fue utilizada")
            cur = con.execute(
                """INSERT INTO certificate_orders(
                   certificate_key_id,user_id,plan_id,udid,device,p12_password,display_name,
                   install_token,install_expires_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (key["id"], user_id, plan_id, udid, device, p12_password, display_name,
                 install_token, install_expires_at, now, now),
            )
            return con.execute("SELECT * FROM certificate_orders WHERE id=?", (cur.lastrowid,)).fetchone()

    def attach_provider_order(self, order_id: int, provider: dict) -> sqlite3.Row:
        code = str(provider.get("order_code") or "").strip()
        if not code:
            raise ValueError("Falta order_code")
        status = str(provider.get("status") or "pending").lower()
        amount = provider.get("amount")
        amount_cents = int(round(float(amount) * 100)) if amount is not None else None
        with self.transaction() as con:
            con.execute(
                """UPDATE certificate_orders SET provider_order_code=?,provider_amount_cents=?,
                   status=?,download_url=?,last_error='',updated_at=? WHERE id=?""",
                (code, amount_cents, status, provider.get("download_url"), utcnow(), order_id),
            )
            if status == "completed":
                con.execute(
                    "UPDATE certificate_orders SET completed_at=COALESCE(completed_at,?), install_expires_at=? WHERE id=?",
                    (utcnow(), (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds"), order_id),
                )
                con.execute(
                    """UPDATE certificate_keys SET status='used' WHERE id=(
                       SELECT certificate_key_id FROM certificate_orders WHERE id=?)""", (order_id,),
                )
            return con.execute("SELECT * FROM certificate_orders WHERE id=?", (order_id,)).fetchone()

    def update_certificate_order(self, provider_order_code: str, provider: dict) -> sqlite3.Row | None:
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM certificate_orders WHERE provider_order_code=?", (provider_order_code,)
            ).fetchone()
            if not row:
                return None
            status = str(provider.get("status") or row["status"]).lower()
            completed_at = provider.get("completed_at") or (utcnow() if status == "completed" else row["completed_at"])
            expires_at = row["install_expires_at"]
            if status == "completed" and row["status"] != "completed":
                expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
            con.execute(
                """UPDATE certificate_orders SET status=?,download_url=COALESCE(?,download_url),
                   p12_password=COALESCE(?,p12_password),completed_at=?,install_expires_at=?,
                   last_error='',updated_at=? WHERE id=?""",
                (status, provider.get("download_url"), provider.get("p12_password"), completed_at,
                 expires_at, utcnow(), row["id"]),
            )
            if status == "completed":
                con.execute("UPDATE certificate_keys SET status='used' WHERE id=?", (row["certificate_key_id"],))
            elif status in ("failed", "cancelled"):
                con.execute("UPDATE certificate_keys SET status='available',redeemed_at=NULL WHERE id=?", (row["certificate_key_id"],))
            return con.execute("SELECT * FROM certificate_orders WHERE id=?", (row["id"],)).fetchone()

    def mark_certificate_error(self, order_id: int, error: str, release_key: bool) -> sqlite3.Row | None:
        with self.transaction() as con:
            row = con.execute("SELECT * FROM certificate_orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                return None
            status = "failed" if release_key else "review"
            con.execute(
                "UPDATE certificate_orders SET status=?,last_error=?,updated_at=? WHERE id=?",
                (status, error[:500], utcnow(), order_id),
            )
            if release_key:
                con.execute(
                    "UPDATE certificate_keys SET status='available',redeemed_at=NULL WHERE id=?",
                    (row["certificate_key_id"],),
                )
            return con.execute("SELECT * FROM certificate_orders WHERE id=?", (order_id,)).fetchone()

    def certificate_order(self, order_id: int, user_id: int | None = None) -> sqlite3.Row | None:
        with self.connect() as con:
            if user_id is None:
                return con.execute("SELECT * FROM certificate_orders WHERE id=?", (order_id,)).fetchone()
            return con.execute(
                "SELECT * FROM certificate_orders WHERE id=? AND user_id=?", (order_id, user_id)
            ).fetchone()

    def renew_certificate_link(self, order_id: int, user_id: int, hours: int = 24) -> sqlite3.Row | None:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
        with self.transaction() as con:
            con.execute("UPDATE certificate_orders SET install_expires_at=? WHERE id=? AND user_id=?",
                        (expires_at, order_id, user_id))
            return con.execute("SELECT * FROM certificate_orders WHERE id=? AND user_id=?",
                               (order_id, user_id)).fetchone()

    def certificate_order_by_code(self, order_code: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM certificate_orders WHERE provider_order_code=?", (order_code,)
            ).fetchone()

    def certificate_orders_for_user(self, user_id: int, udid: str | None = None, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as con:
            if udid:
                return con.execute(
                    "SELECT * FROM certificate_orders WHERE user_id=? AND udid=? COLLATE NOCASE ORDER BY id DESC LIMIT ?",
                    (user_id, udid.strip(), limit),
                ).fetchall()
            return con.execute(
                "SELECT * FROM certificate_orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()

    def pending_certificate_orders(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT * FROM certificate_orders
                   WHERE provider_order_code IS NOT NULL AND (
                       status IN ('pending','processing','review','submitting')
                       OR (status='completed' AND (download_url IS NULL OR delivered_at IS NULL)))
                   ORDER BY updated_at LIMIT ?""", (limit,)
            ).fetchall()

    def install_order(self, token: str) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM certificate_orders WHERE install_token=?", (token,)
            ).fetchone()

    def mark_certificate_delivered(self, order_id: int) -> None:
        with self.transaction() as con:
            con.execute(
                "UPDATE certificate_orders SET delivered_at=COALESCE(delivered_at,?),updated_at=? WHERE id=?",
                (utcnow(), utcnow(), order_id),
            )

    def private_setting(self, key: str) -> str:
        with self.connect() as con:
            row = con.execute("SELECT value FROM private_settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else ""

    def set_private_setting(self, key: str, value: str) -> None:
        with self.transaction() as con:
            con.execute(
                """INSERT INTO private_settings(key,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (key, value, utcnow()),
            )

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
