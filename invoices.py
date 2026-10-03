"""Render immutable purchase records as printable, escaped HTML invoices."""
from html import escape


def invoice_for_order(db, order_id, user_id):
    row = db.execute('''SELECT i.number, i.issued_at, i.currency, i.buyer_email,
        o.id AS order_id, o.product_name, o.quantity, o.unit_price_cents,
        o.quantity * o.unit_price_cents AS total_cents
        FROM invoices i JOIN orders o ON o.id=i.order_id
        WHERE o.id=? AND o.user_id=?''', (order_id, user_id)).fetchone()
    return dict(row) if row else None


def render_invoice(invoice):
    def text(field):
        return escape(str(invoice[field]))
    def money(cents):
        return f'${cents // 100:,}.{cents % 100:02d}'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text('number')} · Stockroom</title><link rel="stylesheet" href="/invoice.css"><script src="/invoice.js" defer></script></head>
<body><nav class="invoice-actions" aria-label="Invoice actions"><a href="/">Back to store</a><button id="print-invoice">Print / Save as PDF</button></nav>
<main><header><div class="brand">stockroom</div><div><h1>Invoice</h1><p>{text('number')}</p></div></header>
<section class="details"><div><h2>Bill to</h2><p>{text('buyer_email')}</p></div><div><h2>Issued</h2><p>{text('issued_at')} UTC</p><p>Order #{text('order_id')} · {text('currency')}</p></div></section>
<table><thead><tr><th>Item</th><th>Quantity</th><th>Unit price</th><th>Amount</th></tr></thead>
<tbody><tr><td>{text('product_name')}</td><td>{text('quantity')}</td><td>{money(invoice['unit_price_cents'])}</td><td>{money(invoice['total_cents'])}</td></tr></tbody></table>
<div class="total"><span>Total · USD</span><strong>{money(invoice['total_cents'])}</strong></div>
<footer><p>Thank you for choosing Stockroom.</p><p>Demo purchase record. No payment collected. Taxes and shipping are not calculated.</p></footer></main></body></html>'''
