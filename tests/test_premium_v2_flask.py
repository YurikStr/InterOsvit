"""Runtime smoke checks; skipped in packaging environment without Flask."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from flask import Flask, redirect
    FLASK_PRESENT=True
except ImportError:
    FLASK_PRESENT=False

@unittest.skipUnless(FLASK_PRESENT,'Flask not available in packaging environment')
class PremiumFlaskTests(unittest.TestCase):
    def setUp(self):
        import premium_v2_store as st
        self.st=st
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        filename=Path(self.tmp.name)/'interosvit.db'
        self.env=patch.dict(os.environ,{'INTEROSVIT_DB_PATH':str(filename),
            'APP_ENV':'development','SUBSCRIPTIONS_TEST_MODE':'true',
            'ENABLE_DEMO_PREMIUM':'false',
            'SUBSCRIPTIONS_TEST_PROVIDER':'local','DEV_USER_ID':'1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        with closing(sqlite3.connect(filename)) as db:
            db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,plan TEXT NOT NULL)')
            db.execute('CREATE TABLE games(id INTEGER PRIMARY KEY)')
            db.executemany('INSERT INTO users VALUES(?,?)',[(1,'free'),(2,'free')])
            db.commit()
        st.migrate()
        database=types.ModuleType('database')
        database.get_user_game_quota=lambda uid: {'plan':self.plan(uid),'limit':5,'used':0,'remaining':5}
        self.patchdb=patch.dict(sys.modules,{'database':database})
        self.patchdb.start()
        self.addCleanup(self.patchdb.stop)
        from premium_v2_routes import premium_v2_bp
        root=Path(__file__).resolve().parents[1]
        self.app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
        self.app.secret_key='test-only-do-not-use-for-real'
        @self.app.get('/login')
        def login():return 'login'
        @self.app.get('/dashboard')
        def dashboard():return 'dashboard'
        self.app.register_blueprint(premium_v2_bp)
        self.client=self.app.test_client()

    def plan(self,uid):
        with closing(self.st.connect()) as db:
            return db.execute('SELECT plan FROM users WHERE id=?',(uid,)).fetchone()['plan']

    def login(self,uid):
        with self.client.session_transaction() as sess:
            sess['user_id']=uid
            sess['premium_v2_csrf']='csrf-test'

    def test_checkout_requires_login_and_csrf_and_developer(self):
        self.assertEqual(self.client.post('/premium-v2/start').status_code,302)
        self.login(2)
        self.assertEqual(self.client.post('/premium-v2/start',data={'premium_v2_csrf':'csrf-test'}).status_code,403)
        self.login(1)
        self.assertEqual(self.client.post('/premium-v2/start').status_code,400)
        self.assertEqual(self.plan(1),'free')
        self.assertEqual(self.client.post('/premium-v2/start',data={'premium_v2_csrf':'csrf-test'}).status_code,302)
        self.assertEqual(self.plan(1),'free')
        self.assertEqual(self.client.post('/premium-v2/simulate',data={'premium_v2_csrf':'csrf-test','event':'success'}).status_code,302)
        self.assertEqual(self.plan(1),'premium')
        self.assertEqual(self.client.get('/premium-v2').status_code,200)
        self.assertEqual(self.client.post('/premium-v2/simulate',data={'premium_v2_csrf':'csrf-test','event':'success'}).status_code,400)

    def test_browser_return_never_activates_and_gateway_closed(self):
        self.login(1)
        self.client.post('/premium-v2/start',data={'premium_v2_csrf':'csrf-test'})
        self.assertEqual(self.client.get('/premium-v2/return').status_code,302)
        self.assertEqual(self.plan(1),'free')
        self.assertEqual(self.client.post('/premium-v2/liqpay/callback',data={'data':'fake','signature':'fake'}).status_code,404)

if __name__=='__main__':unittest.main()
