# Stockroom — Mandai Assessment

A full-stack inventory application with a storefront, admin dashboard, authenticated API, and transactional purchasing. No third-party runtime dependencies.

## Run locally after cloning

Requires Python 3.11+ with SQLite 3.35+ and a modern browser. No package installation, database service, or secret file is needed.

```sh
git clone https://github.com/clementhojjw/mandai-assessment-3Oct2026.git
cd mandai-assessment-3Oct2026
python3 migrate.py
python3 app.py
```

Open http://127.0.0.1:8000/login and choose **Buyer** or **Seller**. Seller uses the admin account and opens the inventory dashboard; Buyer opens the storefront. Sign in with either local demo account:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@stockroom.local` | `AdminDemo!2026` |
| Buyer | `buyer@stockroom.local` | `BuyerDemo!2026` |

These intentionally public credentials are for local interview evaluation only. Use separate browser profiles to operate both roles simultaneously. On Windows, use `py -3` in place of `python3` if needed.

`python3 app.py` also automatically runs pending migrations, so it is enough on its own. The explicit migration command is included above to make setup easy to inspect. The migrations create the schema, both accounts, six products, and invoice records for existing orders. They are versioned, transactional, and safe to rerun: they do not reset inventory or overwrite existing passwords. Existing installations keep their original login credentials.

- Buyer: browse products, choose a quantity, buy, and inspect your order history.
- After buying: select **View invoice**, then **Print / Save as PDF**. Invoices remain available from **My orders**.
- Admin: create, read, update, and remove products; inspect inventory counts and low stock.
- Purchases are simulated: no payment is collected. Invoices are demo purchase records; tax and shipping are not calculated.

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `data/stockroom.db` | SQLite file location |
| `STOCKROOM_ADMIN_PASSWORD` | `AdminDemo!2026` | Override admin password on first migration only |
| `STOCKROOM_BUYER_PASSWORD` | `BuyerDemo!2026` | Override buyer password on first migration only |
| `COOKIE_SECURE` | unset | Set `1` when served over HTTPS |
| `QUIET` | unset | Set `1` to suppress request logs |

`python3 app.py --port 8080` selects another local port. The development server binds to loopback only. `python3 app.py --seed` remains a backwards-compatible alias for migrations.

## Interview walkthrough

1. Run setup and sign in as admin. Create a product with one unit in stock.
2. Sign in as buyer in another browser profile and purchase it. Inspect the invoice and print preview.
3. Return to admin and refresh to see zero stock. An edit from an older form returns a conflict instead of restoring sold inventory.
4. Run the test suite to demonstrate concurrent last-item purchases, safe retries, invoice access control, and migration safety.

## Verify

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```

Node is only needed for the optional JavaScript syntax check. Tests start a real HTTP server and isolated SQLite database. They verify concurrent last-item purchases, duplicate requests, authorization, CSRF protection, stale admin updates, rollback, order privacy, price integrity, CRUD, and logout.

## Repository layout

- `app.py`: HTTP API, authentication, validation, and transaction handling.
- `migrate.py` and `migrations/`: versioned schema changes and demo-account provisioning.
- `schema.sql`: reference schema for application tables.
- `security.py`: shared password hashing.
- `invoices.py`: invoice lookup and printable HTML rendering.
- `static/`: responsive storefront and admin UI with original SVG illustrations.
- `tests/`: HTTP integration, concurrency, invoice, and migration tests.
- `ARCHITECTURE.md`: database schema, endpoints, concurrency proof, and trade-offs.

## Submission

Repository: https://github.com/clementhojjw/mandai-assessment-3Oct2026

See [ARCHITECTURE.md](ARCHITECTURE.md) for the database schema, concurrency strategy, invoice lifecycle, security choices, and technical trade-offs.

Local databases, session data, and custom passwords are excluded from version control. The documented demo accounts are created by the migrations on each fresh checkout.
