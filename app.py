"""Stockroom: standard-library HTTP API and storefront. Python 3.11+."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import re
from migrate import migrate
from security import password_hash
from invoices import invoice_for_order, render_invoice
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DB = os.environ.get('DATABASE_PATH', str(ROOT / 'data' / 'stockroom.db'))
SECURE = os.environ.get('COOKIE_SECURE') == '1'


def connect():
    db = sqlite3.connect(DB, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    migrate(DB)


def seed():
    # Backward-compatible alias. Versioned migrations now own demo provisioning.
    initialize()
    print('Migrations applied. See README.md for demo credentials; existing passwords are preserved.')


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise APIError(400, f'{name} must be an integer between {minimum} and {maximum}.')
    return value


def product_fields(data):
    name, description = data.get('name'), data.get('description', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise APIError(400, 'A product name of 1–120 characters is required.')
    if not isinstance(description, str) or len(description) > 2000:
        raise APIError(400, 'Description must be text under 2,001 characters.')
    return (name.strip(), description, integer(data.get('price_cents'), 'Price', 1, 100000000), integer(data.get('stock'), 'Stock', 0, 1000000))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get('QUIET') != '1':
            super().log_message(fmt, *args)

    def respond(self, status, data, cookie=None):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.common_headers()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def common_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Referrer-Policy', 'same-origin')

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError()
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, 'Send a JSON object smaller than 16 KB.')

    def identity(self, db, role=None, mutate=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            raise APIError(401, 'Please sign in.')
        token = cookie.get('session')
        session = db.execute('SELECT u.id,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?', (hashlib.sha256((token.value if token else '').encode()).hexdigest(), int(time.time()))).fetchone()
        if not session:
            raise APIError(401, 'Please sign in.')
        if role and session['role'] != role:
            raise APIError(403, 'Your account cannot perform this action.')
        if mutate and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
            raise APIError(403, 'Invalid security token. Refresh and try again.')
        return session

    def dispatch(self):
        path = urlsplit(self.path).path
        if not path.startswith('/api/'):
            if self.command != 'GET':
                raise APIError(405, 'Method not allowed.')
            assets = {'/login': ('login.html', 'text/html'), '/login.js': ('login.js', 'text/javascript'), '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml'), '/invoice.css': ('invoice.css', 'text/css'), '/invoice.js': ('invoice.js', 'text/javascript')}
            if path not in assets:
                raise APIError(404, 'Not found.')
            filename, mime = assets[path]
            body = (ROOT / 'static' / filename).read_bytes()
            self.send_response(200)
            self.common_headers()
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        db = connect()
        try:
            method = self.command
            if path == '/api/login' and method == 'POST':
                data = self.body()
                email, password = data.get('email'), data.get('password')
                if not isinstance(email, str) or not isinstance(password, str) or len(password) > 1024:
                    raise APIError(400, 'Email and password are required.')
                user = db.execute('SELECT * FROM users WHERE email=?', (email.strip().lower(),)).fetchone()
                stored = user['password_hash'] if user else '00' * 16 + ':' + '00' * 64
                if not hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored) or not user:
                    raise APIError(401, 'Incorrect email or password.')
                account_type = data.get('account_type')
                if account_type is not None:
                    if account_type not in ('buyer', 'seller'):
                        raise APIError(400, 'Choose Buyer or Seller.')
                    expected_role = 'admin' if account_type == 'seller' else 'user'
                    if user['role'] != expected_role:
                        raise APIError(403, 'This account does not match the selected role. Choose Buyer or Seller to match your account.')
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, int(time.time()) + 28800))
                self.respond(200, {'id': user['id'], 'email': user['email'], 'role': user['role'], 'csrf': csrf}, f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800' + ('; Secure' if SECURE else ''))
                return
            if path == '/api/me' and method == 'GET':
                self.respond(200, dict(self.identity(db)))
                return
            if path == '/api/logout' and method == 'POST':
                session = self.identity(db, mutate=True)
                db.execute('DELETE FROM sessions WHERE user_id=? AND csrf=?', (session['id'], session['csrf']))
                self.respond(200, {'ok': True}, 'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + ('; Secure' if SECURE else ''))
                return
            if path == '/api/products' and method == 'GET':
                self.respond(200, [dict(row) for row in db.execute('SELECT * FROM products WHERE active=1 ORDER BY id')])
                return
            if path == '/api/admin/products':
                self.identity(db, 'admin', mutate=method != 'GET')
                if method == 'GET':
                    self.respond(200, [dict(row) for row in db.execute('SELECT * FROM products WHERE active=1 ORDER BY id')])
                    return
                if method == 'POST':
                    fields = product_fields(self.body())
                    row = db.execute('INSERT INTO products(name,description,price_cents,stock) VALUES (?,?,?,?) RETURNING *', fields).fetchone()
                    self.respond(201, dict(row))
                    return
            if path.startswith('/api/admin/products/'):
                self.identity(db, 'admin', mutate=method != 'GET')
                try:
                    pid = int(path.rsplit('/', 1)[1])
                except ValueError:
                    raise APIError(404, 'Product not found.')
                if method == 'GET':
                    row = db.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()
                    if not row:
                        raise APIError(404, 'Product not found.')
                    self.respond(200, dict(row))
                    return
                if method in ('PUT', 'DELETE'):
                    data = self.body()
                    version = integer(data.get('version'), 'Version', 1, 2**63 - 1)
                    if method == 'PUT':
                        row = db.execute('UPDATE products SET name=?,description=?,price_cents=?,stock=?,version=version+1 WHERE id=? AND version=? AND active=1 RETURNING *', (*product_fields(data), pid, version)).fetchone()
                    else:
                        row = db.execute('UPDATE products SET active=0,version=version+1 WHERE id=? AND version=? AND active=1 RETURNING *', (pid, version)).fetchone()
                    if not row:
                        raise APIError(409, 'Product changed or was removed. Refresh before editing.')
                    self.respond(200, dict(row))
                    return
            invoice_match = re.fullmatch(r'/api/orders/([0-9]{1,18})/invoice(\.html)?', path)
            if invoice_match and method == 'GET':
                user = self.identity(db, 'user')
                invoice = invoice_for_order(db, int(invoice_match[1]), user['id'])
                if not invoice:
                    raise APIError(404, 'Invoice not found.')
                if invoice_match[2]:
                    body = render_invoice(invoice).encode()
                    self.send_response(200)
                    self.common_headers()
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.respond(200, invoice)
                return
            if path == '/api/orders' and method == 'GET':
                user = self.identity(db, 'user')
                self.respond(200, [dict(row) for row in db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY id DESC', (user['id'],))])
                return
            if path == '/api/buy' and method == 'POST':
                user = self.identity(db, 'user', mutate=True)
                data = self.body()
                pid = integer(data.get('product_id'), 'Product ID', 1, 2**63 - 1)
                quantity = integer(data.get('quantity'), 'Quantity', 1, 100)
                key = self.headers.get('Idempotency-Key', '')
                if not 16 <= len(key) <= 128 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in key):
                    raise APIError(400, 'Provide an Idempotency-Key of 16–128 letters, numbers, hyphens or underscores.')
                db.execute('BEGIN IMMEDIATE')
                previous = db.execute('SELECT * FROM orders WHERE user_id=? AND idempotency_key=?', (user['id'], key)).fetchone()
                if previous:
                    if previous['product_id'] != pid or previous['quantity'] != quantity:
                        raise APIError(409, 'This idempotency key was used for a different purchase.')
                    db.commit()
                    self.respond(200, dict(previous))
                    return
                product = db.execute('UPDATE products SET stock=stock-?,version=version+1 WHERE id=? AND active=1 AND stock>=? RETURNING *', (quantity, pid, quantity)).fetchone()
                if not product:
                    raise APIError(409, 'This item is unavailable or there is not enough stock.')
                order = db.execute('INSERT INTO orders(user_id,product_id,product_name,quantity,unit_price_cents,idempotency_key) VALUES (?,?,?,?,?,?) RETURNING *', (user['id'], pid, product['name'], quantity, product['price_cents'], key)).fetchone()
                db.execute('INSERT INTO invoices(order_id,number,buyer_email) VALUES (?,?,?)',
                           (order['id'], f"INV-{order['id']:08d}", user['email']))
                db.commit()
                self.respond(201, dict(order))
                return
            raise APIError(404, 'Endpoint not found.')
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def handle_request(self):
        try:
            self.dispatch()
        except APIError as exc:
            self.respond(exc.status, {'error': exc.message})
        except sqlite3.OperationalError as exc:
            if 'locked' in str(exc):
                self.respond(503, {'error': 'The store is busy. Retry using the same idempotency key.'})
            else:
                self.log_error('Database failure: %s', exc)
                self.respond(500, {'error': 'An unexpected error occurred.'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_error('Request failure: %s', exc)
            self.respond(500, {'error': 'An unexpected error occurred.'})

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', action='store_true')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.seed:
        seed()
    else:
        initialize()
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        print(f'Stockroom running at http://127.0.0.1:{args.port}', flush=True)
        server.serve_forever()
