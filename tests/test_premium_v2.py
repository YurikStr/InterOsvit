import ast
import base64
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import premium_v2_store as st
import premium_v2_gateway as gw
import install_premium_v2 as installer


class PremiumTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db=Path(self.dir.name)/'interosvit.db'
        self.env=patch.dict(os.environ,{'INTEROSVIT_DB_PATH':str(self.db),
             'APP_ENV':'development','SUBSCRIPTIONS_TEST_MODE':'true',
             'ENABLE_DEMO_PREMIUM':'false','DEV_USER_ID':'1'},clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,plan TEXT NOT NULL)')
            db.execute('CREATE TABLE games(id INTEGER PRIMARY KEY)')
            db.execute("INSERT INTO users(id,plan) VALUES(1,'free'),(2,'free'),(3,'premium')")
            db.commit()
        st.migrate()

    def plan(self,user):
        with closing(st.connect()) as db:
            return db.execute('SELECT plan FROM users WHERE id=?',(user,)).fetchone()['plan']

    def test_migrate_repeat_and_explicit_demo_reset(self):
        st.migrate(reset_legacy_demo=True)
        self.assertEqual(self.plan(3),'free')
        self.assertEqual(st.migrate(reset_legacy_demo=True)['reset_demo_count'],0)
        with closing(st.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM io_premium_legacy_plans').fetchone()[0],1)

    def test_payment_controls_premium_and_replay(self):
        o=st.create_order(1,'local')
        self.assertEqual(self.plan(1),'free')
        self.assertEqual(st.create_order(1,'local')['order_id'],o['order_id'])
        self.assertEqual(st.apply_event(o['order_id'],'dev:first','approved','initial'),'activated')
        self.assertEqual(self.plan(1),'premium')
        self.assertEqual(st.apply_event(o['order_id'],'dev:first','approved','initial'),'duplicate')
        self.assertEqual(st.apply_event(o['order_id'],'dev:second','approved','initial'),'ignored')
        self.assertEqual(self.plan(2),'free')

    def test_declined_then_new_checkout(self):
        o=st.create_order(1,'local')
        self.assertEqual(st.apply_event(o['order_id'],'dev:fail','declined','initial'),'declined')
        self.assertEqual(self.plan(1),'free')
        other=st.create_order(1,'local')
        self.assertNotEqual(o['order_id'],other['order_id'])

    def test_cancel_waits_until_period_end(self):
        o=st.create_order(1,'local')
        st.apply_event(o['order_id'],'dev:pay','approved','initial')
        self.assertEqual(st.mark_cancelled(o['order_id'],1),'cancel_pending')
        self.assertEqual(self.plan(1),'premium')
        self.assertEqual(st.apply_event(o['order_id'],'dev:late','approved','renewal'),'ignored')
        st.force_expire_test(o['order_id'],1)
        self.assertEqual(st.expire_due(),1)
        self.assertEqual(self.plan(1),'free')
        self.assertEqual(st.expire_due(),0)

    def test_renewal_one_calendar_month_once(self):
        o=st.create_order(1,'local')
        st.apply_event(o['order_id'],'dev:paid','approved','initial')
        first=st.by_order(o['order_id'])['period_end']
        self.assertEqual(st.apply_event(o['order_id'],'dev:r1','approved','renewal'),'renewed')
        second=st.by_order(o['order_id'])['period_end']
        self.assertGreater(second,first)
        self.assertEqual(st.apply_event(o['order_id'],'dev:r1','approved','renewal'),'duplicate')
        self.assertEqual(st.by_order(o['order_id'])['period_end'],second)

    def test_wrong_user_cannot_cancel(self):
        o=st.create_order(1,'local')
        with self.assertRaises(ValueError):
            st.mark_cancelled(o['order_id'],2)
        self.assertEqual(st.by_order(o['order_id'])['status'],'pending')

    def test_month_clips_last_day(self):
        self.assertEqual(st.add_month(datetime(2026,1,31,tzinfo=timezone.utc)).day,28)

    def test_gateway_signature_and_no_live_keys(self):
        with patch.dict(os.environ,{'LIQPAY_PUBLIC_KEY':'sandbox_public_example',
                  'LIQPAY_PRIVATE_KEY':'sandbox_private_example'}):
            payload={'version':7,'public_key':'sandbox_public_example','status':'sandbox'}
            data=base64.b64encode(json.dumps(payload).encode()).decode()
            sign=gw.signature(data,os.getenv('LIQPAY_PRIVATE_KEY'))
            self.assertEqual(gw.decode_verified_callback(data,sign)['status'],'sandbox')
            with self.assertRaises(ValueError):gw.decode_verified_callback(data,'WRONG')
        with patch.dict(os.environ,{'LIQPAY_PUBLIC_KEY':'live_key','LIQPAY_PRIVATE_KEY':'live_secret'}):
            with self.assertRaises(RuntimeError):gw.merchant_keys()

    def test_installer_patches_old_template_and_app(self):
        app='from flask import Flask\napp = Flask(__name__)\n\nif __name__=="__main__":\n    app.run()\n'
        patched=installer.patch_app(app)
        ast.parse(patched)
        self.assertIn('app.register_blueprint(premium_v2_bp)',patched)
        zipfile=Path(__file__).resolve().parents[2]/'InterOsvit_Premium_Stage1_demo.zip'
        if zipfile.is_file():
            import zipfile as z
            with z.ZipFile(zipfile) as archive:
                pricing=archive.read('interosvit_premium_stage1/templates/pricing.html').decode()
                changed=installer.patch_pricing(pricing)
                self.assertIn('premium_v2.subscription_page',changed)
        else:
            self.skipTest('Old premium template archive not available in the deployment')

if __name__=='__main__': unittest.main()
