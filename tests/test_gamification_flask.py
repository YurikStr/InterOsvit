"""Flask endpoint smoke tests. Auto-skipped if Flask not installed locally."""
import sys
import tempfile
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    from flask import Flask
except ImportError:
    Flask=None


@unittest.skipIf(Flask is None, 'Flask доступний у .venv InterOsvit')
class ProgressPageTests(unittest.TestCase):
    def test_private_user_progress_page(self):
        import gamification_store as store
        import gamification_routes as routes
        with tempfile.TemporaryDirectory() as directory:
            dbpath=Path(directory)/'interosvit.db'
            with closing(sqlite3.connect(dbpath)) as db, db:
                db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);
                      CREATE TABLE games(id INTEGER PRIMARY KEY, game_mode TEXT);
                      CREATE TABLE results(id INTEGER PRIMARY KEY,user_id INTEGER,game_id INTEGER,
                         score INTEGER,total_questions INTEGER,correct_answers INTEGER);
                      INSERT INTO users VALUES(1,'Student');
                      INSERT INTO games VALUES(2,'interactive');''')
            with patch.object(store,'db_path',return_value=dbpath), \
                 patch.object(routes,'get_user_by_id',return_value={'id':1,'username':'Student'}):
                store.migrate()
                app=Flask(__name__,template_folder=str(ROOT/'templates'))
                app.secret_key='test-only-gamification-secret-is-long'
                app.register_blueprint(routes.gamification_bp)
                for endpoint in ('dashboard','login','logout','home'):
                    app.add_url_rule('/'+endpoint,endpoint,lambda:'ok')
                c=app.test_client()
                self.assertEqual(c.get('/my-progress').status_code,302)
                with c.session_transaction() as sess:sess['user_id']=1
                response=c.get('/my-progress')
                self.assertEqual(response.status_code,200)
                self.assertIn('Мої досягнення'.encode(),response.data)
                self.assertIn(b'0 XP',response.data)

if __name__=='__main__':unittest.main()
