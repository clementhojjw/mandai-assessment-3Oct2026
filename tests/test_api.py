import concurrent.futures
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QUIET'] = '1'
        cls.temp = tempfile.TemporaryDirectory()
        app.DB = str(Path(cls.temp.name) / 'test.db')
        app.initialize()
        with app.connect() as db:
            for email, role in [('admin@test.local','admin'),('buyer@test.local','user'),('other@test.local','user')]:
                db.execute('INSERT INTO users(email,password_hash,role) VALUES (?,?,?)',(email,app.password_hash('test-password'),role))
        cls.server = app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.admin,cls.buyer,cls.other = [cls.login(x+'@test.local') for x in ['admin','buyer','other']]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, auth=None, key=None, csrf=True):
        conn = http.client.HTTPConnection('127.0.0.1',cls.server.server_port,timeout=10)
        headers = {'Content-Type':'application/json'}
        if auth:
            headers['Cookie'] = auth['cookie']
            if csrf: headers['X-CSRF-Token'] = auth['csrf']
        if key: headers['Idempotency-Key'] = key
        conn.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
        response = conn.getresponse()
        raw = response.read()
        data = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw.decode()
        status,cookie = response.status,response.getheader('Set-Cookie')
        conn.close()
        return status,data,cookie

    @classmethod
    def login(cls,email):
        status,data,cookie = cls.request('POST','/api/login',{'email':email,'password':'test-password'})
        assert status == 200
        return {'csrf':data['csrf'],'cookie':cookie.split(';')[0]}

    def product(self,stock=1):
        status,data,_ = self.request('POST','/api/admin/products',{'name':'Test item','description':'Test','price_cents':1234,'stock':stock},self.admin)
        self.assertEqual(status,201)
        return data

    def buy(self,pid,key,quantity=1,auth=None):
        return self.request('POST','/api/buy',{'product_id':pid,'quantity':quantity},auth or self.buyer,key)

    def test_last_item_concurrency(self):
        p = self.product(); barrier = threading.Barrier(12)
        def purchase(i):
            barrier.wait()
            return self.buy(p['id'],f'concurrent-key-{i:04d}')[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(purchase,range(12)))
        self.assertEqual(statuses.count(201),1); self.assertEqual(statuses.count(409),11)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT stock FROM products WHERE id=?',(p['id'],)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM orders WHERE product_id=?',(p['id'],)).fetchone()[0],1)

    def test_concurrent_retries(self):
        p = self.product(20); barrier = threading.Barrier(10)
        def purchase(i):
            barrier.wait()
            return self.buy(p['id'],'same-request-key-001')
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(purchase,range(10)))
        self.assertEqual(sum(r[0] == 201 for r in results),1)
        self.assertTrue(all(r[0] in (200,201) for r in results))
        self.assertEqual(len({r[1]['id'] for r in results}),1)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM invoices WHERE order_id=?',(results[0][1]['id'],)).fetchone()[0],1)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT stock FROM products WHERE id=?',(p['id'],)).fetchone()[0],19)

    def test_key_binding_and_user_scope(self):
        p = self.product(4)
        self.assertEqual(self.buy(p['id'],'bound-request-key-01')[0],201)
        self.assertEqual(self.buy(p['id'],'bound-request-key-01',2)[0],409)
        self.assertEqual(self.buy(p['id'],'bound-request-key-01',auth=self.other)[0],201)

    def test_authorization_and_csrf(self):
        self.assertEqual(self.request('GET','/api/admin/products')[0],401)
        self.assertEqual(self.request('GET','/api/admin/products',auth=self.buyer)[0],403)
        self.assertEqual(self.request('POST','/api/admin/products',{},self.admin,csrf=False)[0],403)
        self.assertEqual(self.request('POST','/api/buy',{},self.admin)[0],403)
        self.assertEqual(self.request('POST','/api/buy',{},self.buyer,csrf=False)[0],403)

    def test_stale_admin_edit(self):
        p = self.product(2)
        self.assertEqual(self.buy(p['id'],'admin-race-key-0001')[0],201)
        self.assertEqual(self.request('PUT',f"/api/admin/products/{p['id']}",p,self.admin)[0],409)
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT stock FROM products WHERE id=?',(p['id'],)).fetchone()[0],1)

    def test_rollback(self):
        p = self.product(2)
        with app.connect() as db:
            db.execute(f"CREATE TRIGGER reject_test BEFORE INSERT ON orders WHEN NEW.product_id={p['id']} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        try:
            self.assertEqual(self.buy(p['id'],'rollback-test-key-01')[0],500)
            with app.connect() as db:
                self.assertEqual(db.execute('SELECT stock FROM products WHERE id=?',(p['id'],)).fetchone()[0],2)
        finally:
            with app.connect() as db: db.execute('DROP TRIGGER reject_test')

    def test_delete_preserves_history_and_retries(self):
        p = self.product(2)
        status,order,_ = self.buy(p['id'],'delete-test-key-001'); self.assertEqual(status,201)
        p['version'] += 1
        self.assertEqual(self.request('DELETE',f"/api/admin/products/{p['id']}",p,self.admin)[0],200)
        self.assertEqual(self.buy(p['id'],'delete-test-key-002')[0],409)
        self.assertEqual(self.buy(p['id'],'delete-test-key-001')[1]['id'],order['id'])

    def test_validation_price_and_privacy(self):
        p = self.product(10)
        for quantity in [0,-1,1.5,True,101]:
            self.assertEqual(self.buy(p['id'],'invalid-test-key-01',quantity)[0],400)
        status,order,_ = self.request('POST','/api/buy',{'product_id':p['id'],'quantity':1,'price_cents':1,'user_id':999},self.buyer,'server-price-key-01')
        self.assertEqual(status,201); self.assertEqual(order['unit_price_cents'],1234)
        self.assertNotIn(order['id'],[row['id'] for row in self.request('GET','/api/orders',auth=self.other)[1]])

    def test_invoice_access_and_immutable_values(self):
        p = self.product(4)
        _,order,_ = self.buy(p['id'],'invoice-test-key-01',2)
        path = f"/api/orders/{order['id']}/invoice"
        status,invoice,_ = self.request('GET',path,auth=self.buyer)
        self.assertEqual(status,200)
        self.assertEqual(invoice['number'],f"INV-{order['id']:08d}")
        self.assertEqual(invoice['total_cents'],2468)
        self.assertEqual(invoice['buyer_email'],'buyer@test.local')
        self.assertEqual(self.request('GET',path)[0],401)
        self.assertEqual(self.request('GET',path,auth=self.other)[0],404)
        self.assertEqual(self.request('GET',path,auth=self.admin)[0],403)
        self.assertEqual(self.request('GET',path+'.html',auth=self.other)[0],404)
        with app.connect() as db:
            db.execute('UPDATE products SET name=?,price_cents=? WHERE id=?',('Changed',9999,p['id']))
        self.assertEqual(self.request('GET',path,auth=self.buyer)[1],invoice)
        status,html,_ = self.request('GET',path+'.html',auth=self.buyer)
        self.assertEqual(status,200)
        self.assertIn('$24.68',html)
        self.assertIn('Print / Save as PDF',html)

    def test_invoice_html_escapes_product_text(self):
        p = self.product()
        with app.connect() as db:
            db.execute('UPDATE products SET name=? WHERE id=?',('<script>alert(1)</script>',p['id']))
        _,order,_ = self.buy(p['id'],'invoice-escape-key1')
        _,html,_ = self.request('GET',f"/api/orders/{order['id']}/invoice.html",auth=self.buyer)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertNotIn('<script>alert(1)</script>',html)

    def test_invoice_failure_rolls_back_entire_purchase(self):
        p = self.product(2)
        with app.connect() as db:
            db.execute(f"CREATE TRIGGER reject_invoice BEFORE INSERT ON invoices WHEN (SELECT product_id FROM orders WHERE id=NEW.order_id)={p['id']} BEGIN SELECT RAISE(ABORT, 'injected invoice failure'); END")
        try:
            self.assertEqual(self.buy(p['id'],'invoice-rollback-01')[0],500)
            with app.connect() as db:
                self.assertEqual(db.execute('SELECT stock FROM products WHERE id=?',(p['id'],)).fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM orders WHERE product_id=?',(p['id'],)).fetchone()[0],0)
        finally:
            with app.connect() as db: db.execute('DROP TRIGGER reject_invoice')
        self.assertEqual(self.buy(p['id'],'invoice-rollback-01')[0],201)

    def test_login_role_selection(self):
        for email,password,account_type,expected in [
            ('buyer@test.local','test-password','buyer',200),
            ('admin@test.local','test-password','seller',200),
            ('buyer@test.local','test-password','seller',403),
            ('admin@test.local','test-password','buyer',403),
            ('buyer@test.local','test-password','invalid',400),
        ]:
            status,_,cookie = self.request('POST','/api/login',{'email':email,'password':password,'account_type':account_type})
            self.assertEqual(status,expected)
            if expected != 200:
                self.assertIsNone(cookie)

    def test_crud_and_logout(self):
        p = self.product(3); p['name'] = 'Updated item'; p['stock'] = 8
        status,updated,_ = self.request('PUT',f"/api/admin/products/{p['id']}",p,self.admin)
        self.assertEqual(status,200); self.assertEqual(updated['version'],2)
        self.assertEqual(self.request('GET',f"/api/admin/products/{p['id']}",auth=self.admin)[1]['name'],'Updated item')
        session = self.login('buyer@test.local')
        self.assertEqual(self.request('POST','/api/logout',{},session)[0],200)
        self.assertEqual(self.request('GET','/api/me',auth=session)[0],401)

if __name__ == '__main__': unittest.main(verbosity=2)
