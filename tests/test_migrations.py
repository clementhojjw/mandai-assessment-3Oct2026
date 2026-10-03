import concurrent.futures
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrate
from security import password_hash


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'new.db'

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_setup_and_repeat_preserves_data(self):
        with patch.dict(os.environ, {'STOCKROOM_ADMIN_PASSWORD':'AdminDemo!2026','STOCKROOM_BUYER_PASSWORD':'BuyerDemo!2026'}):
            self.assertEqual(len(migrate.migrate(self.path)),3)
        with sqlite3.connect(self.path) as db:
            for email,role,_,password in migrate.DEMO_ACCOUNTS:
                actual_role,hashed = db.execute('SELECT role,password_hash FROM users WHERE email=?',(email,)).fetchone()
                self.assertEqual(actual_role,role)
                self.assertEqual(password_hash(password,hashed.split(':')[0]),hashed)
            self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0],6)
            db.execute('UPDATE products SET stock=11 WHERE id=1')
            db.execute("UPDATE users SET password_hash='preserved' WHERE role='admin'")
        self.assertEqual(migrate.migrate(self.path),[])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0],11)
            self.assertEqual(db.execute("SELECT password_hash FROM users WHERE role='admin'").fetchone()[0],'preserved')
            self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],3)

    def test_upgrade_legacy_database_backfills_invoices(self):
        with sqlite3.connect(self.path) as db:
            db.executescript((migrate.ROOT/'migrations/001_initial.sql').read_text())
            db.execute("INSERT INTO users VALUES (1,'buyer@stockroom.local','keep-this','user')")
            db.execute("INSERT INTO products(name,price_cents,stock) VALUES ('Legacy',700,2)")
            db.execute("INSERT INTO orders(user_id,product_id,product_name,quantity,unit_price_cents,idempotency_key) VALUES (1,1,'Legacy',2,700,'legacy-order-key')")
        migrate.migrate(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT number,buyer_email FROM invoices').fetchone(),('INV-00000001','buyer@stockroom.local'))
            self.assertEqual(db.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0],'keep-this')
            self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0],1)

    def test_migration_failure_rolls_back_schema_and_ledger(self):
        with patch.object(migrate,'create_demo_data',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): migrate.migrate(self.path)
        with sqlite3.connect(self.path) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables,[])
        self.assertEqual(len(migrate.migrate(self.path)),3)

    def test_concurrent_migrations_apply_once(self):
        # Establish WAL first, then exercise concurrent migration transactions.
        with sqlite3.connect(self.path) as db: db.execute('PRAGMA journal_mode=WAL')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _:migrate.migrate(self.path),range(4)))
        self.assertEqual(sum(len(result) for result in results),3)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],2)

if __name__ == '__main__': unittest.main()
