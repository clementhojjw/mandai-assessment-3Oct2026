# Stockroom architecture

## Scope and invariants

Stockroom is a single-host full-stack demonstration of role-based product management and concurrency-safe buying. A purchase creates one confirmed order and decrements inventory. It does not charge a card, ship a package, or send email.

Core invariants:

1. Inventory cannot become negative.
2. Each successful purchase decrements stock exactly once and has exactly one order and one invoice.
3. A repeated successful purchase key for the same user returns the original order.
4. Reusing a successful key for different purchase parameters fails.
5. Buyers cannot change inventory, prices, roles, or another user's orders.
6. A stale administrator form cannot overwrite stock changed by a purchase.

## Components

The browser loads static HTML, CSS, and JavaScript from the same Python server as the JSON API. Session cookies authenticate API calls. SQLite provides durable relational storage and cross-connection write locking. No in-memory inventory or application mutex participates in the correctness guarantee.

The standard-library server is deliberately a local development server. It uses a separate SQLite connection per request. Production internet exposure requires a hardened HTTP deployment, request/connection limits, HTTPS, authentication throttling, observability, and backup procedures.

## Data model

The executable schema changes are in `migrations/`, applied by `migrate.py`; `schema.sql` is a reference for the application tables.

| Table | Fields and constraints | Purpose |
|---|---|---|
| `users` | Integer primary key; unique email; salted scrypt password hash; role constrained to `admin` or `user` | Authentication and server-side authorization |
| `sessions` | SHA-256 token hash primary key; user foreign key; random CSRF token; expiration timestamp | Revocable eight-hour sessions; raw bearer token exists only in the browser cookie |
| `products` | Integer primary key; name; description; integer `price_cents`; integer `stock`; boolean `active`; version counter | Inventory, price, and optimistic concurrency version |
| `schema_migrations` | Version primary key and applied timestamp | Tracks migration execution |
| `invoices` | Integer primary key; unique order foreign key; unique invoice number; buyer-email snapshot; issue timestamp; currency constrained to USD | Exactly one durable invoice per order |
| `orders` | Integer primary key; user and product foreign keys; product-name snapshot; quantity; unit-price snapshot; idempotency key; UTC creation timestamp | Durable purchase result and deduplication record |

`UNIQUE(user_id, idempotency_key)` prevents duplicate successful operations per buyer. An index on `(user_id, id)` supports private order-history queries. Money uses integer cents in one currency, USD. Product prices are restricted to 1–100,000,000 cents and stock to 0–1,000,000 units. Quantity is an integer from 1–100. Booleans and fractional quantities are rejected by request validation.

Product deletion is soft deletion (`active=0`). Historical orders retain their foreign keys, name snapshots, and price snapshots. Orders are immutable in this scope. There is no public registration or role-assignment endpoint; initial demo accounts are provisioned by migration 002.

## API contract

All mutation bodies are JSON objects. Responses are JSON; errors have an `error` string. Authenticated mutations require both the session cookie and `X-CSRF-Token` returned by login or `/api/me`.

| Method | Path | Access | Behavior |
|---|---|---|---|
| POST | `/api/login` | Public | Accept email/password; issue session cookie and CSRF token |
| GET | `/api/me` | Signed in | Current identity, role, and CSRF token |
| POST | `/api/logout` | Signed in + CSRF | Revoke current session |
| GET | `/api/products` | Public | List active products |
| GET | `/api/admin/products` | Admin | List active inventory |
| GET | `/api/admin/products/:id` | Admin | Read one active product |
| POST | `/api/admin/products` | Admin + CSRF | Create product |
| PUT | `/api/admin/products/:id` | Admin + CSRF | Replace editable fields, requiring current version |
| DELETE | `/api/admin/products/:id` | Admin + CSRF | Soft-delete, requiring current version |
| POST | `/api/buy` | User + CSRF | Atomically create purchase; require `Idempotency-Key` |
| GET | `/api/orders/:id/invoice` | User | Invoice JSON, restricted to the order owner |
| GET | `/api/orders/:id/invoice.html` | User | Printable invoice HTML, restricted to the order owner |
| GET | `/api/orders` | User | Only the authenticated buyer's orders |

Create/edit product fields: `name`, `description`, `price_cents`, and `stock`. Edit/delete additionally require `version`. The server ignores any client-supplied role, buyer ID, or purchase price.

A buy request contains `{"product_id": 1, "quantity": 2}` and an `Idempotency-Key` header of 16–128 ASCII alphanumeric characters, hyphens or underscores. The UI generates a UUID for each intended purchase. New purchases return 201; successful replays return 200 with the same order. Validation errors return 400, missing/expired sessions 401, forbidden roles or invalid CSRF 403, and stock/version/key conflicts 409. Lock timeout returns 503 so the caller can retry with the same key.

## Purchase transaction and concurrency strategy

SQLite uses database-level write serialization, not row-level `SELECT FOR UPDATE`. Every buy executes this sequence on one connection:

```sql
BEGIN IMMEDIATE;
-- Look up (authenticated user_id, supplied idempotency_key).
-- If found: compare product_id and quantity, then return the original order.

UPDATE products
SET stock = stock - :quantity, version = version + 1
WHERE id = :product_id AND active = 1 AND stock >= :quantity
RETURNING *;

-- If zero rows: roll back and return 409.
-- Otherwise use the returned server-side name and price:
INSERT INTO orders (...);
INSERT INTO invoices (...);
COMMIT;
```

The code acquires SQLite's write reservation before reading the deduplication record. Another buyer must wait until the current transaction commits or rolls back. Once admitted, that buyer sees the latest stock and any committed deduplication record. WAL mode allows ordinary readers alongside the writer, but does not allow multiple concurrent writers. The five-second busy timeout bounds waiting.

For one remaining unit and two distinct requests, the first transaction updates stock from one to zero and inserts its order. The second transaction's conditional update matches no row and fails without an order. The database `CHECK(stock >= 0)` is an additional backstop. Stock decrement, order insertion, and invoice creation cannot commit independently.

For concurrent duplicate keys, the first transaction commits one order. Subsequent transactions find that order and return it without another decrement. If the body differs, they return a conflict. Keys are scoped by buyer so different users cannot retrieve each other's orders through matching keys.

### Crash and retry behavior

- Crash before commit: SQLite rolls back the uncommitted transaction; neither effect persists.
- Order or invoice insertion failure: rollback restores the stock decrement and removes any uncommitted order.
- Commit succeeds but HTTP response is lost: the retry finds the committed order and returns it.
- Lock contention: return 503 after the bounded wait; retry the same key.
- Insufficient stock: no result is persisted. Retrying after restock can succeed. Only successful purchases are permanently deduplicated.

Order records are retained, so successful keys do not expire in this implementation. Deleting historical orders would weaken that guarantee and is not supported. The browser saves pending keys and their exact payloads in session storage before sending. It retains them for ambiguous network/server failures and uses the same key for retries. This is a convenience, not the core guarantee: a client that loses its key and invents a new one is creating a new operation. A production multi-device client should provide explicit unresolved-purchase recovery.

### Administrator concurrency

Every sale and inventory edit increments `products.version`. Administrator edits and removals use `WHERE id=? AND version=? AND active=1`. If a sale occurs after an admin loads the form, that form's update matches no row and returns 409. The admin must refresh and reconsider the intended stock value. If the admin update happens first, the subsequent buyer observes the newly committed state.

Absolute stock editing is kept for this exercise. A production warehouse usually needs an append-only stock-movement ledger for receipts, adjustments, returns, and auditing.

## Security choices

Passwords use scrypt with per-account random salts. Session tokens have 256 bits of random input and only token hashes are stored. Cookies are HttpOnly and SameSite=Strict; HTTPS deployments must set `COOKIE_SECURE=1`. Sessions expire after eight hours and logout revokes the current token.

The server checks the database role on every protected request. Browser navigation visibility is only presentation. CSRF tokens protect authenticated mutations; JSON content-type enforcement and lack of cross-origin CORS access prevent ordinary cross-site login form submissions. SQL values are bound parameters. Product text is HTML-escaped before insertion into templates. The server sends a same-origin content security policy, disallows framing, disables MIME sniffing, and marks API responses `no-store`.

The application limits JSON request size, validates numeric bounds, reads purchase prices from the database, and scopes order history by session identity. It does not trust client identity or totals.

## Trade-offs and production evolution

- **SQLite over PostgreSQL:** zero setup and actual transactional safety make the sample easy to evaluate. A single writer limits throughput, and the file must stay on a reliable local disk shared by the single deployment. Do not deploy separate independent database copies or use a network filesystem. PostgreSQL would support independent row locks and greater concurrent write throughput.
- **Plain browser JavaScript over a framework:** no build chain and a small auditable submission. Larger applications would benefit from component architecture, routing, static types, and richer UI testing.
- **Standard-library HTTP server:** runnable without package installation; not a production HTTP serving stack. Production needs bounded concurrency, body read timeouts, authentication rate limits, TLS termination, monitoring, and operational hardening.
- **Session authentication:** immediate revocation and straightforward role enforcement, at the cost of database lookup per request. Password reset, MFA, account administration, expired-session cleanup, and brute-force protection are outside this demo.
- **Single-product orders:** keeps locking simple. Multi-product orders require one transaction covering all line items, and deterministic lock order on a row-locking database.
- **No external payment:** the guarantee covers the local inventory/order transaction only. Real payments require reservations and explicit states such as pending, confirmed, expired, and cancelled; provider idempotency and reconciliation; and an outbox for durable downstream events. A database transaction alone cannot make external side effects exactly once.
- **No checkout price quote:** the authoritative price is the price at commit time. A real checkout should validate an accepted quote/version so a price change cannot surprise a customer.
- **Small custom migration runner:** sufficient for this local exercise. Migrations and their version ledger commit atomically; a larger team should use a mature migration framework with schema-drift and checksum detection. Add bounded lists, audit logging, backups, and performance monitoring as data and traffic grow.

## Verification

`python3 -m unittest discover -s tests -v` launches the actual HTTP handler with an isolated temporary SQLite file. It tests:

1. Twelve simultaneous requests for the last item: one order, eleven conflicts, zero stock.
2. Ten simultaneous identical keys: one created order, nine replays, one decrement.
3. Key-to-payload binding and separation between buyers.
4. Authentication, admin authorization, and CSRF enforcement.
5. A stale administrator update after a purchase cannot restore old stock.
6. Injected order-insert failure rolls back the stock decrement.
7. Soft deletion preserves historical orders and successful retry results.
8. Invalid quantities are rejected; spoofed prices and identities are ignored; order history is private.
9. Admin create/read/update operations and session invalidation on logout.
10. Invoice ownership checks for JSON and HTML, accurate totals, and stable purchase snapshots after product edits.
11. Escaping of product text in invoice HTML.
12. Invoice-insert failure rolls back both the order and stock change.
13. Fresh migrations create usable admin and buyer credentials; repeats preserve data.
14. Legacy databases receive invoices without losing accounts, passwords, or products.
15. Migration failure rolls back schema and version ledger together.
16. Concurrent migration runners apply each migration only once.

Tests use real database transactions and separate HTTP connections rather than mocks. They validate correctness under modest contention, not production throughput or a distributed deployment. Process-kill fault injection, browser automation, and production load testing are additional future verification work.


## Invoice lifecycle

Invoice creation is automatic inside the buy transaction. A unique foreign key to `orders.id` prevents multiple invoices for one order. The number is `INV-` plus the zero-padded order ID, such as `INV-00000001`; it is stable across purchase retries. An existing successful purchase returns without creating another invoice.

The invoice stores its buyer email, issue date, and USD currency. Item name and unit price come from the immutable order snapshot, not the current catalog. Totals are calculated in integer cents from quantity multiplied by the snapshotted price. The invoice is not marked paid because this demo has no payment integration. Tax and shipping calculations are explicitly outside scope.

Both JSON and HTML invoice routes authenticate the buyer and filter by order ownership. Missing invoices and another buyer's invoices both return 404. Admin credentials do not grant invoice access in this implementation. Responses use `Cache-Control: no-store`; all rendered customer/product text is escaped. The invoice opens in a separate tab and has a print stylesheet; the browser's print dialog can save it as PDF without a server-side PDF dependency.

## Reproducible setup and upgrades

`python3 migrate.py` opens the configured SQLite database, enables foreign keys and WAL, and applies these versions under `BEGIN IMMEDIATE`:

- `001_initial`: create the original application tables if absent, so legacy installations can be adopted.
- `002_demo_accounts_and_products`: insert the admin and buyer accounts if missing, with scrypt-hashed documented demo passwords; insert the initial products only when the catalog is empty.
- `003_invoices`: create the invoice table and backfill an invoice for every existing order using its original creation time.

Every applied version is recorded in `schema_migrations` in the same transaction as its changes. A failed migration rolls back the entire pending batch. The implementation executes complete SQL statements individually because Python's `executescript()` implicitly commits and would break the intended atomic boundary. Concurrent runners serialize through SQLite's write lock and check versions after acquiring it.

Server startup invokes the same migration runner automatically. The old `--seed` command remains an alias. Repeated starts never replenish stock, recreate removed products, or reset existing account passwords. Password environment overrides affect first creation only. The public default passwords are an explicit local-demo convenience and must be replaced for an actual deployment. No existing local database or session file is committed to the repository.

## Buyer and Seller login page

`/login` provides an accessible Buyer/Seller radio selection. Seller maps to the existing `admin` role; Buyer maps to `user`. The login API accepts optional `account_type` (`buyer` or `seller`) and verifies it against the stored role after password verification, before creating a session. A role mismatch returns 403 without issuing a session cookie. The selection cannot grant privileges. The optional field preserves compatibility with existing API clients. Successful seller login opens inventory, while buyer login opens the storefront.
