"""Versioned, transactional local-demo migrations. Run: python3 migrate.py."""
import os
from pathlib import Path
import sqlite3
from security import password_hash

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'data' / 'stockroom.db'
DEMO_ACCOUNTS = (
    ('admin@stockroom.local', 'admin', 'STOCKROOM_ADMIN_PASSWORD', 'AdminDemo!2026'),
    ('buyer@stockroom.local', 'user', 'STOCKROOM_BUYER_PASSWORD', 'BuyerDemo!2026'),
)


def execute_sql(db, filename):
    # executescript() implicitly commits: execute complete statements individually
    # so the schema changes and migration ledger remain one atomic transaction.
    statement = ''
    for line in (ROOT / 'migrations' / filename).read_text().splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ''
    if statement.strip():
        raise ValueError(f'Incomplete SQL in {filename}')


def create_demo_data(db):
    for email, role, env_name, default in DEMO_ACCOUNTS:
        # Preserve existing accounts and passwords when upgrading an older checkout.
        if not db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
            db.execute('INSERT INTO users(email,password_hash,role) VALUES (?,?,?)',
                       (email, password_hash(os.environ.get(env_name, default)), role))
    if not db.execute('SELECT 1 FROM products').fetchone():
        db.executemany('INSERT INTO products(name,description,price_cents,stock) VALUES (?,?,?,?)', [
            ('Everyday tote', 'Heavyweight cotton. Made for the daily essentials.', 2800, 24),
            ('Studio notebook', 'A quiet space for your next big idea. 160 ruled pages.', 1600, 38),
            ('Ceramic cup', 'A warm ivory glaze and a comfortable, generous handle.', 3200, 7),
            ('Desk tray', 'Keep the little things in order. Solid natural oak.', 4200, 12),
            ('Field bottle', 'Insulated stainless steel for wherever the day goes.', 3600, 18),
            ('Canvas pouch', 'A small home for cables, pens, and loose ends.', 1800, 0),
        ])


def apply_migrations(db):
    applied = []
    migrations = (
        ('001_initial', lambda: execute_sql(db, '001_initial.sql')),
        ('002_demo_accounts_and_products', lambda: create_demo_data(db)),
        ('003_invoices', lambda: execute_sql(db, '003_invoices.sql')),
    )
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version, apply in migrations:
            if not db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
                apply()
                db.execute('INSERT INTO schema_migrations(version) VALUES (?)', (version,))
                applied.append(version)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return applied


def migrate(database_path=None):
    path = Path(database_path or os.environ.get('DATABASE_PATH', DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        return apply_migrations(db)
    finally:
        db.close()


if __name__ == '__main__':
    versions = migrate()
    print('Applied: ' + ', '.join(versions) if versions else 'Database is up to date.')
    print('Fresh demo accounts: admin@stockroom.local / AdminDemo!2026; buyer@stockroom.local / BuyerDemo!2026')
    print('Existing passwords are preserved. Environment password overrides apply only on first creation.')
