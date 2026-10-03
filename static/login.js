'use strict';
const form = document.getElementById('login-form');
const error = document.getElementById('login-error');
const submit = document.getElementById('login-submit');
const picker = form.querySelector('fieldset');
const requestedRole = new URLSearchParams(location.search).get('role');
if (requestedRole === 'seller') form.elements.account_type.value = 'seller';
function updateRole() {
  const seller = form.elements.account_type.value === 'seller';
  document.getElementById('login-title').textContent = seller ? 'Seller sign in' : 'Buyer sign in';
  document.getElementById('login-description').textContent = seller
    ? 'Manage products, update stock, and keep your store running.'
    : 'Shop the collection and access your orders and invoices.';
  submit.textContent = seller ? 'Sign in as Seller' : 'Sign in as Buyer';
  error.textContent = '';
}
form.querySelectorAll('[name="account_type"]').forEach(input => input.addEventListener('change', updateRole));
updateRole();
form.addEventListener('submit', async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form));
  submit.disabled = true;
  picker.disabled = true;
  error.textContent = '';
  submit.textContent = 'Signing in…';
  try {
    const response = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to sign in. Please try again.');
    // The server's verified role determines the destination, never the role picker alone.
    location.assign(result.role === 'admin' ? '/?view=admin' : '/');
  } catch (failure) {
    updateRole();
    error.textContent = failure.message || 'Unable to connect. Please try again.';
    submit.disabled = false;
    picker.disabled = false;
  }
});
