PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','user'))
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
 description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 1 AND 100000000),
 stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 1000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 100),
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents > 0),
 idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, id);
