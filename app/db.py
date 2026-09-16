from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite


class StoreDB:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                balance_cents INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                price_usd REAL NOT NULL DEFAULT 0, sale_price_usd REAL,
                delivery_type TEXT, stock INTEGER, image_url TEXT, active INTEGER NOT NULL DEFAULT 1,
                raw_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, quantity INTEGER NOT NULL, amount_usd REAL NOT NULL,
                provider_amount_usd REAL, provider_order_id INTEGER, status TEXT NOT NULL,
                customer_reference TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
                activation_identifier TEXT, result_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL,
                type TEXT NOT NULL, amount_cents INTEGER NOT NULL, balance_after_cents INTEGER NOT NULL,
                reference TEXT NOT NULL, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                status TEXT NOT NULL, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(telegram_user_id);
            CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_transactions(telegram_user_id);
            """)
            await self._add_column(db, "products", "sale_price_usd", "REAL")
            await self._add_column(db, "products", "active", "INTEGER NOT NULL DEFAULT 1")
            await self._add_column(db, "orders", "provider_amount_usd", "REAL")
            await self._add_column(db, "users", "language", "TEXT NOT NULL DEFAULT 'ar'")
            await db.execute("UPDATE products SET sale_price_usd=price_usd WHERE sale_price_usd IS NULL")
            await db.commit()

    async def _add_column(self, db: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
        cur = await db.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cur.fetchall()}
        if column not in columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    async def upsert_user(self, telegram_id: int, username: str | None, first_name: str | None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""INSERT INTO users(telegram_id,username,first_name) VALUES(?,?,?)
            ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,updated_at=CURRENT_TIMESTAMP""", (telegram_id, username, first_name))
            await db.commit()

    async def user(self, telegram_id: int) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
            return await cur.fetchone()

    async def set_language(self, telegram_id: int, language: str) -> None:
        if language not in {"ar", "en"}:
            raise ValueError("unsupported language")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET language=?,updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?", (language, telegram_id))
            await db.commit()

    async def replace_products(self, products: list[dict[str, Any]]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE products SET active=0")
            for p in products:
                delivery_type = p.get("delivery_type", "")
                stock = p.get("stock")
                active = 0 if delivery_type == "stock" and stock is not None and int(stock) <= 0 else 1
                await db.execute("""INSERT INTO products(id,name,description,price_usd,sale_price_usd,delivery_type,stock,image_url,active,raw_json)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
                price_usd=excluded.price_usd,delivery_type=excluded.delivery_type,stock=excluded.stock,image_url=excluded.image_url,
                active=excluded.active,raw_json=excluded.raw_json,updated_at=CURRENT_TIMESTAMP""", (p["id"], p.get("name", ""), p.get("description", ""), p.get("price_usd", 0), round(float(p.get("price_usd", 0)) * 1.30, 2), delivery_type, stock, p.get("image_url"), active, json.dumps(p, ensure_ascii=False)))
            await db.commit()

    async def products(self, active_only: bool = True) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE active=1" if active_only else ""
            cur = await db.execute(f"SELECT * FROM products {where} ORDER BY id")
            return await cur.fetchall()

    async def product(self, product_id: int) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,))
            return await cur.fetchone()

    async def set_sale_price(self, product_id: int, sale_price_usd: float) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("UPDATE products SET sale_price_usd=? WHERE id=?", (round(sale_price_usd, 2), product_id))
            await db.commit()
            return cur.rowcount == 1

    async def wallet_balance_cents(self, user_id: int) -> int:
        row = await self.user(user_id)
        return int(row["balance_cents"]) if row else 0

    async def credit_wallet(self, user_id: int, amount_cents: int, reference: str, note: str = "") -> int:
        if amount_cents <= 0:
            raise ValueError("amount must be positive")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO users(telegram_id) VALUES(?) ON CONFLICT(telegram_id) DO NOTHING", (user_id,))
            cur = await db.execute("SELECT balance_cents FROM users WHERE telegram_id=?", (user_id,))
            current = int((await cur.fetchone())[0])
            new_balance = current + amount_cents
            await db.execute("UPDATE users SET balance_cents=?,updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?", (new_balance, user_id))
            await db.execute("INSERT INTO wallet_transactions(telegram_user_id,type,amount_cents,balance_after_cents,reference,note) VALUES(?,?,?,?,?,?)", (user_id, "CREDIT", amount_cents, new_balance, reference, note))
            await db.commit()
            return new_balance

    async def credit_wallet_once(self, user_id: int, amount_cents: int, reference: str, note: str = "") -> int:
        if amount_cents <= 0:
            raise ValueError("amount must be positive")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT balance_after_cents FROM wallet_transactions WHERE reference=? LIMIT 1", (reference,))
            existing = await cur.fetchone()
            if existing:
                await db.commit()
                return int(existing[0])
            await db.execute("INSERT INTO users(telegram_id) VALUES(?) ON CONFLICT(telegram_id) DO NOTHING", (user_id,))
            cur = await db.execute("SELECT balance_cents FROM users WHERE telegram_id=?", (user_id,))
            current = int((await cur.fetchone())[0])
            new_balance = current + amount_cents
            await db.execute("UPDATE users SET balance_cents=?,updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?", (new_balance, user_id))
            await db.execute("INSERT INTO wallet_transactions(telegram_user_id,type,amount_cents,balance_after_cents,reference,note) VALUES(?,?,?,?,?,?)", (user_id, "CREDIT", amount_cents, new_balance, reference, note))
            await db.commit()
            return new_balance

    async def debit_wallet(self, user_id: int, amount_cents: int, reference: str, note: str = "") -> int:
        if amount_cents <= 0:
            raise ValueError("amount must be positive")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT balance_cents,blocked FROM users WHERE telegram_id=?", (user_id,))
            row = await cur.fetchone()
            if not row or row[1]:
                await db.rollback()
                raise ValueError("USER_BLOCKED_OR_MISSING")
            current = int(row[0])
            if current < amount_cents:
                await db.rollback()
                raise ValueError("INSUFFICIENT_BALANCE")
            new_balance = current - amount_cents
            await db.execute("UPDATE users SET balance_cents=?,updated_at=CURRENT_TIMESTAMP WHERE telegram_id=?", (new_balance, user_id))
            await db.execute("INSERT INTO wallet_transactions(telegram_user_id,type,amount_cents,balance_after_cents,reference,note) VALUES(?,?,?,?,?,?)", (user_id, "DEBIT", -amount_cents, new_balance, reference, note))
            await db.commit()
            return new_balance

    async def refund_wallet(self, user_id: int, amount_cents: int, reference: str, note: str = "") -> int:
        return await self.credit_wallet(user_id, amount_cents, reference, note)

    async def create_order(self, user_id: int, product_id: int, quantity: int, sale_amount: float, provider_amount: float, reference: str, idem: str, activation: str | None = None) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("INSERT INTO orders(telegram_user_id,product_id,quantity,amount_usd,provider_amount_usd,status,customer_reference,idempotency_key,activation_identifier) VALUES(?,?,?,?,?,?,?,?,?)", (user_id, product_id, quantity, sale_amount, provider_amount, "PAID", reference, idem, activation))
            await db.execute("INSERT INTO order_events(order_id,status,detail) VALUES(?,?,?)", (cur.lastrowid, "PAID", "wallet payment confirmed"))
            await db.commit()
            return int(cur.lastrowid)

    async def update_provider_order(self, local_id: int, provider_id: int, status: str, result_json: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET provider_order_id=?,status=?,result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (provider_id, status, result_json, local_id))
            await db.execute("INSERT INTO order_events(order_id,status,detail) VALUES(?,?,?)", (local_id, status, result_json[:1000]))
            await db.commit()

    async def order(self, local_id: int) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT o.*,p.name product_name FROM orders o LEFT JOIN products p ON p.id=o.product_id WHERE o.id=?", (local_id,))
            return await cur.fetchone()

    async def user_orders(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT o.*,p.name product_name FROM orders o LEFT JOIN products p ON p.id=o.product_id WHERE telegram_user_id=? ORDER BY o.id DESC LIMIT ?", (user_id, limit))
            return await cur.fetchall()

    async def admin_orders(self, limit: int = 15) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT o.*,p.name product_name FROM orders o LEFT JOIN products p ON p.id=o.product_id ORDER BY o.id DESC LIMIT ?", (limit,))
            return await cur.fetchall()

    async def admin_users(self, limit: int = 15) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users ORDER BY updated_at DESC LIMIT ?", (limit,))
            return await cur.fetchall()

    async def stats(self) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*),COALESCE(SUM(amount_usd),0) FROM orders")
            orders, revenue = await cur.fetchone()
            cur = await db.execute("SELECT COUNT(*),COALESCE(SUM(balance_cents),0) FROM users")
            users, stored = await cur.fetchone()
            return {"orders": orders, "revenue": revenue, "users": users, "stored_cents": stored}
