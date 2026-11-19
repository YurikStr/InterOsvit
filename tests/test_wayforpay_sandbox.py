import hashlib
from contextlib import closing
import hmac
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import install_wayforpay_test as installer
import wayforpay_test_gateway as gateway
import wayforpay_test_store as store

ENV={
    'APP_ENV':'development',
    'SUBSCRIPTIONS_TEST_MODE':'true',
    'WAYFORPAY_TEST_MODE':'true',
    'SUBSCRIPTIONS_TEST_PROVIDER':'local',
    'PREMIUM_V2_PUBLIC_BASE_URL':'https://test.example.ngrok-free.dev',
}


def payload_for(order,merchant='test_merch_n1',status='Approved',amount='99.00'):
    p=dict(merchantAccount=merchant,orderReference=order['order_ref'],amount=amount,
           currency='UAH',authCode='123456',cardPan='42****1234',
           transactionStatus=status,reasonCode='1100')
    p['merchantSignature']=gateway.hmac_md5(p[k] for k in ('merchantAccount','orderReference',
        'amount','currency','authCode','cardPan','transactionStatus','reasonCode'))
    return p

class WayForPaySandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{**ENV,'WAYFORPAY_TEST_DB_PATH':str(Path(self.temp.name)/'wfp.db')})
        self.env.start()
        self.addCleanup(self.env.stop)
    def test_test_only_environment(self):
        for k,v in [('APP_ENV','production'),('WAYFORPAY_TEST_MODE','false'),
                    ('SUBSCRIPTIONS_TEST_MODE','false'),('SUBSCRIPTIONS_TEST_PROVIDER','liqpay')]:
            with self.subTest(k=k),patch.dict(os.environ,{k:v}):
                with self.assertRaises(RuntimeError): gateway.sandbox_guard()
    def test_public_https_origin_required(self):
        for b in ['http://example.com','https://localhost:5051','https://example.com/path',
                  'https://example.com?token=bad','https://x:y@example.com']:
            with self.subTest(base=b),patch.dict(os.environ,{'PREMIUM_V2_PUBLIC_BASE_URL':b}):
                with self.assertRaises(RuntimeError): gateway.public_base()
    def test_purchase_signature_and_one_time_only(self):
        order=store.new_order(3)
        fields=gateway.purchase_fields(order)
        self.assertEqual(fields['regularMode'],'none')
        self.assertEqual(fields['amount'],'99.00')
        self.assertEqual(fields['currency'],'UAH')
        self.assertEqual(fields['serviceUrl'],'https://test.example.ngrok-free.dev/wayforpay-test/callback')
        tosign=['test_merch_n1','test.example.ngrok-free.dev',order['order_ref'],str(order['order_date']),
                '99.00','UAH',gateway.PRODUCT,'1','99.00']
        manual=hmac.new(gateway.TEST_SECRET.encode(),';'.join(tosign).encode(),hashlib.md5).hexdigest()
        self.assertEqual(fields['merchantSignature'],manual)
        self.assertEqual(gateway.PAY_URL,'https://secure.wayforpay.com/pay')
    def test_verified_callback_and_duplicate(self):
        order=store.new_order(3)
        payload=payload_for(order)
        gateway.verify_callback(payload)
        self.assertEqual(store.apply_verified_callback(payload),'approved')
        self.assertEqual(store.get(order['order_ref'])['status'],'approved')
        self.assertEqual(store.apply_verified_callback(payload),'duplicate')
    def test_reject_bad_signature_and_wrong_merchant(self):
        order=store.new_order(3)
        p=payload_for(order)
        p['merchantSignature']='0'*32
        with self.assertRaises(ValueError):gateway.verify_callback(p)
        wrong=payload_for(order,merchant='live_merchant')
        with self.assertRaises(ValueError):gateway.verify_callback(wrong)
    def test_no_callback_without_required_fields(self):
        order=store.new_order(3)
        p=payload_for(order)
        del p['authCode']
        with self.assertRaises(ValueError):gateway.verify_callback(p)
    def test_reject_fractional_amount(self):
        for bad in ['99.001','NaN','Infinity','-1','abc',True]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):gateway.minor_from_amount(bad)
    def test_declined_stays_declined(self):
        order=store.new_order(3)
        p=payload_for(order,status='Declined')
        gateway.verify_callback(p)
        self.assertEqual(store.apply_verified_callback(p),'declined')
        self.assertEqual(store.get(order['order_ref'])['status'],'declined')
        approved=payload_for(order)
        self.assertEqual(store.apply_verified_callback(approved),'ignored')
    def test_no_real_premium_tables(self):
        import sqlite3
        store.new_order(3)
        with closing(sqlite3.connect(str(store.db_path()))) as c:
            names={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names,{'wfp_test_orders'})
    def test_installer_static_patch(self):
        app='from flask import Flask\napp=Flask(__name__)\nfrom premium_v2_routes import premium_v2_bp\napp.register_blueprint(premium_v2_bp)\n'
        patched=installer.patch_source(app)
        self.assertIn('app.register_blueprint(wayforpay_test_bp)',patched)
        self.assertIsNone(installer.patch_source(patched))
    def test_signed_ack(self):
        a=gateway.acknowledgment('wfptest_123456789012',1763251200)
        self.assertEqual(a['status'],'accept')
        self.assertEqual(a['signature'],gateway.hmac_md5(('wfptest_123456789012','accept',1763251200)))

if __name__=='__main__':unittest.main()
