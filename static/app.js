'use strict';
const $ = id => document.getElementById(id);
let user = null, products = [], editing = null, selected = null, purchaseKey = null, purchasePayload = null;
const money = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(cents / 100);
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
async function api(path, {method = 'GET', body, key} = {}) {
  const headers = {'Content-Type':'application/json'};
  if (user) headers['X-CSRF-Token'] = user.csrf;
  if (key) headers['Idempotency-Key'] = key;
  const response = await fetch('/api' + path, {method, headers, body:body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || 'Request failed.'); error.status = response.status; throw error; }
  return data;
}
let noticeTimer;
function notify(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 5000); }
function show(view) {
  for (const name of ['shop','orders','admin']) { $(name).hidden = name !== view; $(name + '-nav').classList.toggle('selected', name === view); }
  if (view === 'orders') loadOrders().catch(error => notify(error.message));
  if (view === 'admin') loadAdmin().catch(error => notify(error.message));
}
function accountUI() {
  $('account').textContent = user ? 'Sign out' : 'Sign in ↗';
  $('admin-nav').hidden = user?.role !== 'admin';
  $('orders-nav').hidden = user?.role !== 'user';
}
const illustrations = [
  '<path d="M49 58 Q49 12 85 12 Q121 12 121 58" fill="none" stroke="#847a60" stroke-width="9"/><path d="M31 49 L139 49 L150 149 L20 149 Z" fill="#cabc99"/><path d="M41 54 L34 141 M130 54 L137 141" stroke="#b0a07c" fill="none"/><text x="85" y="108" text-anchor="middle" fill="#635f4b" font-family="Georgia" font-size="24">s.</text>',
  '<rect x="38" y="15" width="100" height="135" rx="4" fill="#526b4e"/><path d="M48 15 V150" stroke="#374f37" stroke-width="3"/><path d="M128 19 V146" stroke="#dddccb" stroke-width="6"/><rect x="64" y="42" width="49" height="36" fill="#dde2ce"/><path d="M72 54 H105 M76 63 H101" stroke="#7b8d6a"/>',
  '<ellipse cx="77" cy="139" rx="53" ry="9" fill="#cebaa4"/><path d="M118 61 C165 46 165 121 119 112" fill="none" stroke="#e1ccb4" stroke-width="14"/><path d="M28 51 H125 L117 122 Q114 145 77 145 Q38 145 35 122 Z" fill="#f2e6d7"/><ellipse cx="77" cy="51" rx="49" ry="12" fill="#c1a58c"/><ellipse cx="77" cy="53" rx="41" ry="8" fill="#695448"/>',
  '<path d="M12 81 L96 39 L162 74 L79 128 Z" fill="#b59063"/><path d="M12 81 V99 L79 143 L162 91 V74 L79 128 Z" fill="#96734c"/><path d="M25 80 L96 47 L148 74 L78 115 Z" fill="#d2b38a"/><path d="M45 79 L99 55 M65 91 L118 65" stroke="#c5a275"/>',
  '<rect x="62" y="15" width="46" height="24" rx="5" fill="#4e6257"/><rect x="55" y="33" width="60" height="116" rx="23" fill="#7a9180"/><path d="M67 49 V127" stroke="#a6b5a5" stroke-width="5" stroke-linecap="round"/><path d="M62 31 H108" stroke="#394f43" stroke-width="3"/>',
  '<path d="M21 55 L145 55 L154 137 Q85 154 15 137 Z" fill="#b79779"/><path d="M23 56 H142" stroke="#615b4c" stroke-width="5"/><path d="M29 64 H138" stroke="#d0b496"/><path d="M137 54 L153 72" stroke="#60574a" stroke-width="4"/><rect x="67" y="88" width="34" height="24" fill="#e0cdb1"/>'
];
function hasPending(id) { return user && sessionStorage.getItem(`purchase:${user.id}:${id}`); }
function renderProducts() {
  $('product-count').textContent = `${products.length} essentials`;
  $('products').innerHTML = products.length ? products.map((p, i) => `<article class="card"><div class="product-art tone-${i % 6}"><svg aria-hidden="true" viewBox="0 0 170 165">${illustrations[i % 6]}</svg>${p.stock === 0 ? '<span class="soldout">Sold out</span>' : ''}</div><div class="card-title"><h3>${escapeHTML(p.name)}</h3><span>${money(p.price_cents)}</span></div><p>${escapeHTML(p.description)}</p><div class="card-bottom"><span>${p.stock ? `${p.stock} available` : 'Back soon'}</span><button class="outline" data-buy="${p.id}" ${p.stock === 0 && !hasPending(p.id) ? 'disabled' : ''}>${hasPending(p.id) ? 'Check purchase ↗' : p.stock ? 'Buy now ↗' : 'Sold out'}</button></div></article>`).join('') : '<p class="empty">The collection is being refreshed. Check back soon.</p>';
}
async function loadProducts() { products = await api('/products'); renderProducts(); }
async function loadOrders() {
  const orders = await api('/orders');
  $('order-list').innerHTML = orders.length ? orders.map(o => `<article class="order"><div><h3>${escapeHTML(o.product_name)}</h3><p>Order #${o.id} · ${escapeHTML(o.created_at)} UTC</p><p>Quantity ${o.quantity} × ${money(o.unit_price_cents)}</p></div><div class="order-total"><h3>${money(o.quantity * o.unit_price_cents)}</h3><span class="pill">Confirmed</span><p><a class="invoice-link" href="/api/orders/${o.id}/invoice.html" target="_blank" rel="noopener">View invoice ↗</a></p></div></article>`).join('') : '<p class="empty">Your first good find is waiting in the shop.</p>';
}
async function loadAdmin() {
  products = await api('/admin/products');
  $('stats').innerHTML = [['Products',products.length],['Units available',products.reduce((n,p) => n+p.stock,0)],['Low stock',products.filter(p => p.stock <= 5).length]].map(([label,value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`).join('');
  $('inventory').innerHTML = products.map(p => `<tr><td>${escapeHTML(p.name)}</td><td>${money(p.price_cents)}</td><td>${p.stock}</td><td><span class="pill ${p.stock === 0 ? 'out' : p.stock <= 5 ? 'low' : ''}">${p.stock === 0 ? 'Sold out' : p.stock <= 5 ? 'Low stock' : 'In stock'}</span></td><td><div class="actions"><button class="text-button" data-edit="${p.id}">Edit</button><button class="text-button danger" data-delete="${p.id}">Remove</button></div></td></tr>`).join('');
}
for (const view of ['shop','orders','admin']) $(view+'-nav').onclick = () => { show(view); if (view === 'shop') loadProducts().catch(e => notify(e.message)); };
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => $(button.dataset.close).close());
$('account').onclick = async () => {
  if (!user) { location.assign('/login'); return; }
  try { await api('/logout',{method:'POST',body:{}}); user = null; accountUI(); $('purchase-success').hidden = true; show('shop'); notify('You are signed out.'); } catch(e) { notify(e.message); }
};
$('products').onclick = event => {
  const button = event.target.closest('[data-buy]'); if (!button) return;
  if (!user) { location.assign('/login?role=buyer'); return; }
  if (user.role !== 'user') { notify('Sign in with a buyer account to place an order.'); return; }
  selected = products.find(p => p.id === Number(button.dataset.buy));
  // Keep unresolved requests across dialog closes, reloads and network errors.
  const saved = JSON.parse(sessionStorage.getItem(`purchase:${user.id}:${selected.id}`) || 'null');
  purchaseKey = saved?.key || crypto.randomUUID(); purchasePayload = saved?.payload || null;
  $('quantity').value = purchasePayload?.quantity || 1; $('quantity').disabled = !!purchasePayload;
  $('purchase-title').textContent = selected.name;
  $('purchase-detail').textContent = `${money(selected.price_cents)} each · ${selected.stock} available`;
  $('purchase-error').textContent = saved ? 'A previous purchase has an unconfirmed result. Retry to check it safely.' : '';
  $('buy-button').textContent = saved ? 'Retry purchase' : 'Confirm purchase';
  updateTotal(); $('purchase-dialog').showModal();
};
function updateTotal() { $('purchase-total').textContent = 'Total ' + money(selected.price_cents * Number($('quantity').value)); }
$('quantity').oninput = updateTotal;
$('purchase-form').onsubmit = async event => {
  event.preventDefault(); const button = $('buy-button'); button.disabled = true;
  const storageKey = `purchase:${user.id}:${selected.id}`;
  purchasePayload = purchasePayload || {product_id:selected.id,quantity:Number($('quantity').value)};
  sessionStorage.setItem(storageKey,JSON.stringify({key:purchaseKey,payload:purchasePayload})); $('quantity').disabled = true;
  try {
    const order = await api('/buy',{method:'POST',body:purchasePayload,key:purchaseKey});
    sessionStorage.removeItem(storageKey); $('purchase-dialog').close();
    $('purchase-success-detail').textContent = `Order #${order.id} · ${money(order.quantity * order.unit_price_cents)} · Your invoice is ready.`;
    $('latest-invoice').href = `/api/orders/${order.id}/invoice.html`;
    $('purchase-success').hidden = false;
    $('purchase-success').scrollIntoView({behavior:'smooth', block:'start'});
    notify(`Order #${order.id} confirmed. Your invoice is ready.`);
    loadProducts().catch(() => notify('Purchase confirmed. Refresh the page to update inventory.'));
  } catch(e) {
    $('purchase-error').textContent = e.message;
    if (e.status && e.status < 500) { sessionStorage.removeItem(storageKey); purchasePayload = null; $('quantity').disabled = false; }
    button.textContent = 'Retry purchase';
  } finally { button.disabled = false; }
};
function openEditor(product=null) {
  editing = product; $('product-form').reset(); $('product-error').textContent = '';
  $('editor-title').textContent = product ? 'Edit product' : 'Add product';
  if (product) { const f = $('product-form').elements; f.name.value = product.name; f.description.value = product.description; f.price.value = (product.price_cents / 100).toFixed(2); f.stock.value = product.stock; }
  $('product-dialog').showModal();
}
$('new-product').onclick = () => openEditor();
$('refresh').onclick = () => loadAdmin().catch(e => notify(e.message));
$('inventory').onclick = async event => {
  const edit = event.target.closest('[data-edit]'), remove = event.target.closest('[data-delete]');
  if (edit) openEditor(products.find(p => p.id === Number(edit.dataset.edit)));
  if (remove) {
    const product = products.find(p => p.id === Number(remove.dataset.delete));
    if (!confirm(`Remove ${product.name} from the storefront? Existing orders will be preserved.`)) return;
    try { await api('/admin/products/'+product.id,{method:'DELETE',body:{version:product.version}}); await loadAdmin(); notify('Product removed.'); } catch(e) { notify(e.message); }
  }
};
$('product-form').onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  const f = Object.fromEntries(new FormData(event.target));
  const body = {name:f.name,description:f.description,price_cents:Math.round(Number(f.price)*100),stock:Number(f.stock),...(editing ? {version:editing.version} : {})};
  try { await api('/admin/products'+(editing ? '/'+editing.id : ''),{method:editing ? 'PUT' : 'POST',body}); $('product-dialog').close(); await loadAdmin(); notify('Product saved.'); } catch(e) { $('product-error').textContent = e.message; } finally { button.disabled = false; }
};
(async () => {
  try { user = await api('/me'); } catch(e) { if (e.status !== 401) notify(e.message); }
  accountUI();
  if (user?.role === 'admin' && new URLSearchParams(location.search).get('view') === 'admin') show('admin');
  try { await loadProducts(); } catch(e) { $('products').textContent = 'Unable to load the collection. Refresh to try again.'; }
})();
