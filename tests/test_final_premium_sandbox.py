"""OFFLINE Premium/LiqPay Sandbox behavior tests.

Uses a temporary SQLite database and invented sandbox credentials. Never
connects to a payment provider. Requires the installed Flask app environment.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
READY = bool(importlib.util.find_spec('flask')
             and importlib.util.find_spec('premium_v2_store')
             and importlib.util.find_spec('premium_v2_routes')
             and importlib.util.find_spec('premium_v2_gateway'))


@unittest.skipUnless(READY, 'Потрібні Flask і встановлений Premium v2; запусти всередині C:\\InterOsvit')
class FinalPremiumSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'interosvit.db'
        self.env = patch.dict(os.environ, {
            'INTEROSVIT_DB_PATH': str(path),
            'APP_ENV': 'development',
            'SUBSCRIPTIONS_TEST_MODE': 'true',
            'ENABLE_DEMO_PREMIUM': 'false',
            'SUBSCRIPTIONS_TEST_PROVIDER': 'liqpay',
            'DEV_USER_ID': '3',
            'LIQPAY_PUBLIC_KEY': 'sandbox_i_offline_test_000',
            'LIQPAY_PRIVATE_KEY': 'sandbox_offline_private_000',
            'PREMIUM_V2_PUBLIC_BASE_URL': 'https://callback.example.org',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        with closing(sqlite3.connect(str(path))) as conn:
            conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, plan TEXT NOT NULL)')
            conn.execute('CREATE TABLE games(id INTEGER PRIMARY KEY)')
            conn.executemany('INSERT INTO users(id,plan) VALUES (?,?)',
                             [(2, 'free'), (3, 'free')])
            conn.commit()
        from flask import Flask
        import premium_v2_store as store
        import premium_v2_gateway as gateway
        from premium_v2_routes import premium_v2_bp
        self.store = store
        self.gateway = gateway
        store.migrate()
        dbmodule = types.ModuleType('database')
        def get_user_game_quota(uid):
            return {'plan': self.plan(uid), 'limit': 5, 'used': 0, 'remaining': 5}
        dbmodule.get_user_game_quota = get_user_game_quota
        self.dbpatch = patch.dict(sys.modules, {'database': dbmodule})
        self.dbpatch.start()
        self.addCleanup(self.dbpatch.stop)
        app = Flask(__name__, template_folder=str(ROOT/'templates'),
                    static_folder=str(ROOT/'static'))
        app.secret_key = 'offline-sandbox-tests-only'
        @app.get('/login')
        def login(): return 'test login'
        @app.get('/dashboard')
        def dashboard(): return 'test dashboard'
        app.register_blueprint(premium_v2_bp)
        self.client = app.test_client()

    def plan(self, user_id):
        with closing(self.store.connect()) as conn:
            item = conn.execute('SELECT plan FROM users WHERE id=?', (user_id,)).fetchone()
            return item['plan'] if item else None

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['premium_v2_csrf'] = 'offline-test-csrf'

    def start(self, user_id=3):
        self.login(user_id)
        result = self.client.post('/premium-v2/start',
                                  data={'premium_v2_csrf': 'offline-test-csrf'})
        return result

    def sign_callback(self, order, *, status='sandbox', action='subscribe',
                      amount='99.00', currency='UAH', payment_id='offline-payment-1'):
        payload = {
            'version': 7, 'public_key': 'sandbox_i_offline_test_000',
            'order_id': order['order_id'], 'amount': amount, 'currency': currency,
            'status': status, 'action': action, 'payment_id': payment_id,
        }
        data = self.gateway._encode(payload)
        return {'data': data,
                'signature': self.gateway.signature(data, 'sandbox_offline_private_000')}

    def test_signed_callback_activates_only_once(self):
        self.assertEqual(self.start().status_code, 302)
        self.assertEqual(self.plan(3), 'free')
        order = self.store.latest_for_user(3)
        self.assertEqual(order['provider'], 'liqpay')
        result = self.client.post('/premium-v2/liqpay/callback',
                                  data=self.sign_callback(order))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.plan(3), 'premium')
        first_end = self.store.by_order(order['order_id'])['period_end']
        result2 = self.client.post('/premium-v2/liqpay/callback',
                                   data=self.sign_callback(order))
        self.assertEqual(result2.status_code, 200)
        self.assertEqual(self.store.by_order(order['order_id'])['period_end'], first_end)
        self.assertEqual(self.plan(2), 'free')

    def test_browser_return_cannot_activate_and_wrong_signature_rejected(self):
        self.start()
        order = self.store.latest_for_user(3)
        self.assertEqual(self.client.get('/premium-v2/return').status_code, 302)
        self.assertEqual(self.plan(3), 'free')
        invalid = self.sign_callback(order)
        invalid['signature'] = 'fake'
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback', data=invalid).status_code, 400)
        self.assertEqual(self.plan(3), 'free')

    def test_wrong_amount_and_currency_rejected(self):
        self.start()
        order = self.store.latest_for_user(3)
        for change in ({'amount': '1.00'}, {'currency': 'USD'}):
            self.assertEqual(self.client.post('/premium-v2/liqpay/callback',
                              data=self.sign_callback(order, **change)).status_code, 400)
            self.assertEqual(self.plan(3), 'free')

    def test_failure_keeps_free(self):
        self.start()
        order = self.store.latest_for_user(3)
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback',
            data=self.sign_callback(order, status='failure')).status_code, 200)
        self.assertEqual(self.plan(3), 'free')
        self.assertEqual(self.store.latest_for_user(3)['status'], 'failed')

    def test_renewal_and_duplicate_event(self):
        self.start()
        order = self.store.latest_for_user(3)
        self.client.post('/premium-v2/liqpay/callback', data=self.sign_callback(order))
        before = self.store.by_order(order['order_id'])['period_end']
        renewal = self.sign_callback(order, action='regular', status='sandbox', payment_id='offline-renewal-1')
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback', data=renewal).status_code, 200)
        after = self.store.by_order(order['order_id'])['period_end']
        self.assertGreater(after, before)
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback', data=renewal).status_code, 200)
        self.assertEqual(self.store.by_order(order['order_id'])['period_end'], after)

    def test_unknown_order_and_wrong_merchant_rejected(self):
        self.start()
        order = self.store.latest_for_user(3)
        unknown = dict(self.sign_callback(order))
        # Signed payload for a different order must never mutate the account.
        payload = {
            'version': 7, 'public_key': 'sandbox_i_offline_test_000',
            'order_id': 'not-existing-order', 'amount': '99.00',
            'currency': 'UAH', 'status': 'sandbox', 'action': 'subscribe',
            'payment_id': 'offline-other-payment',
        }
        data = self.gateway._encode(payload)
        unknown = {'data': data,
                   'signature': self.gateway.signature(data, 'sandbox_offline_private_000')}
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback', data=unknown).status_code, 404)
        self.assertEqual(self.plan(3), 'free')
        payload['order_id'] = order['order_id']
        payload['public_key'] = 'sandbox_another_merchant'
        data = self.gateway._encode(payload)
        merchant = {'data': data,
                    'signature': self.gateway.signature(data, 'sandbox_offline_private_000')}
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback', data=merchant).status_code, 400)
        self.assertEqual(self.plan(3), 'free')

    def test_cancel_preserves_premium_only_when_provider_confirms(self):
        self.start()
        order = self.store.latest_for_user(3)
        self.client.post('/premium-v2/liqpay/callback', data=self.sign_callback(order))
        self.assertEqual(self.plan(3), 'premium')
        with patch('premium_v2_routes.gateway.cancel_renewals', return_value=False):
            self.assertEqual(self.client.post('/premium-v2/cancel',
                data={'premium_v2_csrf': 'offline-test-csrf'}).status_code, 302)
        self.assertEqual(self.store.by_order(order['order_id'])['status'], 'active')
        with patch('premium_v2_routes.gateway.cancel_renewals', return_value=True):
            self.assertEqual(self.client.post('/premium-v2/cancel',
                data={'premium_v2_csrf': 'offline-test-csrf'}).status_code, 302)
        self.assertEqual(self.store.by_order(order['order_id'])['status'], 'cancel_pending')
        self.assertEqual(self.plan(3), 'premium')
        self.store.force_expire_test(order['order_id'], 3)
        self.store.expire_due()
        self.assertEqual(self.plan(3), 'free')

    def test_only_local_developer_can_start_liqpay_checkout(self):
        # If this fails, install_liqpay_sandbox.py from Step2 is missing.
        self.assertEqual(self.start(user_id=2).status_code, 403)
        self.assertIsNone(self.store.latest_for_user(2))
        self.assertEqual(self.start(user_id=3).status_code, 302)
        order = self.store.latest_for_user(3)
        self.login(2)
        self.assertEqual(self.client.get('/premium-v2/checkout/'+order['order_id']).status_code, 403)


if __name__ == '__main__':
    unittest.main()
