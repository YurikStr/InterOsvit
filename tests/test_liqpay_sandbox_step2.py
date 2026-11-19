"""Offline tests. No requests to LiqPay, no card data, no real DB."""
import base64
from contextlib import contextmanager
import http.client
import json
import importlib.util
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_liqpay_sandbox as installer
import liqpay_callback_relay as relay


class OfflineLiqpayTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{
            'APP_ENV':'development','SUBSCRIPTIONS_TEST_MODE':'true',
            'ENABLE_DEMO_PREMIUM':'false','SUBSCRIPTIONS_TEST_PROVIDER':'liqpay',
            'LIQPAY_PUBLIC_KEY':'sandbox_i0000000','LIQPAY_PRIVATE_KEY':'sandbox_test_private_key_123',
            'PREMIUM_V2_PUBLIC_BASE_URL':'https://only-webhook.trycloudflare.com',
            'DEV_USER_ID':'3'
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    @unittest.skipUnless(importlib.util.find_spec("premium_v2_gateway"), "Existing premium_v2_gateway.py is not bundled; run tests inside InterOsvit")
    def test_sign_and_validate_test_callback(self):
        import premium_v2_gateway as gateway
        fields=gateway.checkout_fields({'amount_minor':9900,'currency':'UAH','order_id':'io2_abc'})
        encoded=json.loads(base64.b64decode(fields['data']))
        self.assertEqual(encoded['sandbox'],'1')
        self.assertEqual(encoded['action'],'subscribe')
        self.assertEqual(encoded['server_url'], 'https://only-webhook.trycloudflare.com/premium-v2/liqpay/callback')
        self.assertEqual(encoded['result_url'], 'https://only-webhook.trycloudflare.com/premium-v2/return')
        self.assertEqual(encoded['amount'],99.0)
        callback=gateway._encode({'version':7,'public_key':'sandbox_i0000000', 'order_id':'io2_abc', 'amount':'99.00', 'currency':'UAH','status':'sandbox', 'action':'subscribe'})
        self.assertEqual(gateway.decode_verified_callback(callback,gateway.signature(callback,'sandbox_test_private_key_123'))['status'],'sandbox')
        with self.assertRaises(ValueError):
            gateway.decode_verified_callback(callback,'bad_signature')

    @unittest.skipUnless(importlib.util.find_spec("premium_v2_gateway"), "Existing premium_v2_gateway.py is not bundled; run tests inside InterOsvit")
    def test_reject_live_key_or_production(self):
        import premium_v2_gateway as gateway
        with patch.dict(os.environ, {'LIQPAY_PUBLIC_KEY':'i0000000'}):
            with self.assertRaises(RuntimeError): gateway.merchant_keys()
        with patch.dict(os.environ, {'APP_ENV':'production'}):
            with self.assertRaises(RuntimeError): gateway.merchant_keys()
            with self.assertRaises(RuntimeError): relay.assert_sandbox()

    def test_installer_known_routes_and_template(self):
        root=Path(__file__).resolve().parents[1]
        source=root/'premium_v2_routes.py'
        template=root/'templates'/'premium_v2.html'
        # Runs on user's machine with original source; when packaging source missing, skip.
        if not source.is_file() or not template.is_file():
            self.skipTest('Original Premium v2 routes not in stand-alone patch directory')
        text=source.read_text(encoding='utf-8')
        tpl=template.read_text(encoding='utf-8')
        if 'def liqpay_developer_only' in text:
            self.assertNotIn('{% if not local or dev %}',tpl)
        else:
            self.assertIn('liqpay_developer_only(user_id)',installer.transform_routes(text))
            self.assertIn('{% if dev %}',installer.transform_template(tpl))

    def test_relay_accepts_only_callback_and_return(self):
        class MockResponse:
            status=200
            def __enter__(self):return self
            def __exit__(self,*x):return False
        with relay.ThreadingHTTPServer(('127.0.0.1',0),relay.CallbackOnlyHandler) as server:
            thread=threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host,port=server.server_address
            try:
                conn=http.client.HTTPConnection(host,port,timeout=3)
                conn.request('GET','/')
                self.assertEqual(conn.getresponse().status,404)
                conn.close()
                conn=http.client.HTTPConnection(host,port,timeout=3)
                conn.request('GET','/premium-v2/return')
                response=conn.getresponse()
                self.assertEqual(response.status,302)
                self.assertEqual(response.getheader('Location'),'http://127.0.0.1:5000/premium-v2/return')
                conn.close()
                conn=http.client.HTTPConnection(host,port,timeout=3)
                with patch.object(relay, 'urlopen', return_value=MockResponse()) as post:
                    conn.request('POST','/premium-v2/liqpay/callback',body='data=hi&signature=ho',headers={'Content-Type':'application/x-www-form-urlencoded'})
                    self.assertEqual(conn.getresponse().status,200)
                    args,kwargs=post.call_args
                    self.assertEqual(args[0].full_url,'http://127.0.0.1:5000/premium-v2/liqpay/callback')
                conn.close()
                conn=http.client.HTTPConnection(host,port,timeout=3)
                conn.request('POST','/login',body='x=1',headers={'Content-Type':'application/x-www-form-urlencoded'})
                self.assertEqual(conn.getresponse().status,404)
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=3)

if __name__=='__main__': unittest.main()
