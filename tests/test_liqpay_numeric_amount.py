"""Fast offline regression for Checkout amount numeric type."""
import base64
import json
import os
import unittest
from unittest.mock import patch
import premium_v2_gateway as gateway


class CheckoutRequestFormatTests(unittest.TestCase):
    def test_checkout_request_is_numeric_and_test_only(self):
        env = {
            'APP_ENV':'development',
            'SUBSCRIPTIONS_TEST_MODE':'true',
            'ENABLE_DEMO_PREMIUM':'false',
            'LIQPAY_PUBLIC_KEY':'sandbox_i_testing',
            'LIQPAY_PRIVATE_KEY':'sandbox_private_testing',
            'PREMIUM_V2_PUBLIC_BASE_URL':'https://test-connection.ngrok-free.dev'
        }
        with patch.dict(os.environ, env):
            f = gateway.checkout_fields({'order_id':'io2_fake','amount_minor':9900,'currency':'UAH'})
            data = json.loads(base64.b64decode(f['data'],validate=True))
            self.assertEqual(data['action'], 'subscribe')
            self.assertEqual(data['sandbox'], '1')
            self.assertEqual(data['amount'], 99.0)
            self.assertIsInstance(data['amount'], (int,float))
            self.assertEqual(f['action'], gateway.CHECKOUT_URL)
            self.assertEqual(data['version'], 7)
            self.assertEqual(f['signature'], gateway.signature(f['data'],env['LIQPAY_PRIVATE_KEY']))


if __name__ == '__main__':
    unittest.main()
