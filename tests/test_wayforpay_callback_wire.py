"""Offline tests for the format-only WayForPay callback relay correction.

Does not create payments, reach the Internet, or modify the app DB.
"""
import json
import unittest
from pathlib import Path
import sys
import os
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / 'wayforpay_callback_relay.py'


def read_normalizer():
    import ast
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    names = {'_unique_object', '_strict_json_object', 'normalize_callback_body'}
    selections = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {n.name for n in selections} != names:
        raise RuntimeError('Install the fix first: relay parser is missing')
    stub = ast.fix_missing_locations(ast.Module(body=selections, type_ignores=[]))
    ns = {'json': json, 'parse_qsl': __import__('urllib.parse', fromlist=['parse_qsl']).parse_qsl}
    exec(compile(stub, str(SOURCE), 'exec'),ns)
    return ns['normalize_callback_body']


class WayForPayCallbackWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parse = staticmethod(read_normalizer())

    def test_form_fields(self):
        p = {'merchantAccount': 'test_merch_n1', 'amount': '99.00', 'currency':'UAH',
             'merchantSignature': 'a'*32}
        self.assertEqual(json.loads(self.parse('application/x-www-form-urlencoded',
                                              urlencode(p).encode())),p)

    def test_form_wrapped_data(self):
        p={'merchantAccount':'test_merch_n1','amount':99}
        body=urlencode({'data': json.dumps(p)}).encode()
        self.assertEqual(json.loads(self.parse('application/x-www-form-urlencoded',body)),p)

    def test_form_wrapped_payload(self):
        p={'transactionStatus':'Declined'}
        body=urlencode({'payload':json.dumps(p)}).encode()
        self.assertEqual(json.loads(self.parse('application/x-www-form-urlencoded',body)),p)

    def test_mislabeled_raw_json(self):
        raw=b'{"transactionStatus":"Declined"}'
        self.assertEqual(json.loads(self.parse('application/x-www-form-urlencoded',raw)),
                         {'transactionStatus':'Declined'})

    def test_json_passthrough(self):
        raw=b'{"merchantAccount":"test_merch_n1"}'
        self.assertEqual(self.parse('application/json',raw),raw)

    def test_reject_duplicate_form_keys(self):
        with self.assertRaises(ValueError):
            self.parse('application/x-www-form-urlencoded',b'amount=99&amount=1')

    def test_reject_duplicate_json_keys(self):
        with self.assertRaises(ValueError):
            self.parse('application/json',b'{"amount":99,"amount":1}')

    def test_reject_empty_or_invalid_form(self):
        for raw in (b'',b'broken',b'&',b'amount=%XX&bad',b'=bad'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                self.parse('application/x-www-form-urlencoded',raw)

    def test_reject_oversized_form(self):
        with self.assertRaises(ValueError):
            self.parse('application/x-www-form-urlencoded',b'a='+(b'a'*32768))

    def test_reject_unsupported_content_type(self):
        with self.assertRaises(ValueError):
            self.parse('text/plain',b'{"amount":99}')

    def test_reject_non_object_json(self):
        for raw in (b'[]',b'null',b'"hello"',b'{}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                self.parse('application/json',raw)

    def test_valid_signed_sandbox_form_is_preserved(self):
        import wayforpay_test_gateway as gateway
        p = {'merchantAccount':'test_merch_n1',
             'orderReference':'wfptest_1234567890123456',
             'amount':'99.00', 'currency':'UAH', 'authCode':'123456',
             'cardPan':'42****1234','transactionStatus':'Declined',
             'reasonCode':'1100'}
        p['merchantSignature']=gateway.hmac_md5(p[k] for k in
            ('merchantAccount','orderReference','amount','currency','authCode',
             'cardPan','transactionStatus','reasonCode'))
        body = urlencode(p).encode()
        normalized = json.loads(self.parse('application/x-www-form-urlencoded',body))
        env={'APP_ENV':'development','SUBSCRIPTIONS_TEST_MODE':'true',
             'SUBSCRIPTIONS_TEST_PROVIDER':'local','WAYFORPAY_TEST_MODE':'true'}
        with patch.dict(os.environ,env):
            gateway.verify_callback(normalized)
            self.assertEqual(gateway.minor_from_amount(normalized['amount']),9900)

    def test_tampered_signed_form_is_rejected(self):
        import wayforpay_test_gateway as gateway
        p = {'merchantAccount':'test_merch_n1',
             'orderReference':'wfptest_1234567890123456',
             'amount':'99.00', 'currency':'UAH', 'authCode':'123456',
             'cardPan':'42****1234','transactionStatus':'Declined',
             'reasonCode':'1100'}
        p['merchantSignature']=gateway.hmac_md5(p[k] for k in
            ('merchantAccount','orderReference','amount','currency','authCode',
             'cardPan','transactionStatus','reasonCode'))
        p['amount']='100.00'
        normalized=json.loads(self.parse('application/x-www-form-urlencoded',urlencode(p).encode()))
        env={'APP_ENV':'development','SUBSCRIPTIONS_TEST_MODE':'true',
             'SUBSCRIPTIONS_TEST_PROVIDER':'local','WAYFORPAY_TEST_MODE':'true'}
        with patch.dict(os.environ,env):
            with self.assertRaises(ValueError):
                gateway.verify_callback(normalized)

    def test_duplicate_wrapped_json_key_rejected(self):
        body=urlencode({'json':'{"merchantAccount":"test_merch_n1","merchantAccount":"bad"}'}).encode()
        with self.assertRaises(ValueError):
            self.parse('application/x-www-form-urlencoded',body)

if __name__ == '__main__':
    unittest.main()
