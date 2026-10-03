CREATE TABLE invoices (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
 number TEXT NOT NULL UNIQUE,
 buyer_email TEXT NOT NULL,
 issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency = 'USD')
);
-- Existing orders receive the same durable invoice that new purchases receive.
INSERT INTO invoices(order_id, number, buyer_email, issued_at)
SELECT o.id, printf('INV-%08d', o.id), u.email, o.created_at
FROM orders o JOIN users u ON u.id = o.user_id;
