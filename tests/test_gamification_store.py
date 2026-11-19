"""SQLite tests without Flask or network. Run: python -m unittest ..."""
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import gamification_store as store


class GamificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'interosvit.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);
                CREATE TABLE games(id INTEGER PRIMARY KEY, game_mode TEXT);
                CREATE TABLE results(id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL, game_id INTEGER NOT NULL,
                   score INTEGER, total_questions INTEGER, correct_answers INTEGER,
                   completed_at TEXT DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO users(id,username) VALUES(1,'Learner'),(2,'Other');
                INSERT INTO games(id,game_mode) VALUES(24,'matching'),(23,'true_false');
                INSERT INTO results(user_id,game_id,score,total_questions,correct_answers)
                    VALUES(1,24,4,5,4);
            ''')
        self.pp = patch.object(store, 'db_path', return_value=self.path)
        self.pp.start()
        self.addCleanup(self.pp.stop)

    def test_migrate_backfill_only_once(self):
        self.assertEqual(store.migrate()['imported'], 1)
        self.assertTrue(store.migrate()['already_migrated'])
        with closing(store.connect_db()) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM gamification_attempts').fetchone()[0], 1)
        self.assertEqual(store.progress_for_user(1)['xp'], store.xp_for(4,5))
        self.assertEqual(store.progress_for_user(1)['best_streak'], 0)
        self.assertEqual(store.progress_for_user(2)['xp'], 0)

    def test_points_and_streaks(self):
        self.assertEqual(store.xp_for(3, 5, 3), 46)
        self.assertEqual(store.xp_for(5, 5, 5), 90)
        self.assertEqual(store.streak_stats([True,True,False,True,True,True]), (3,3))
        with self.assertRaises(ValueError):
            store.streak_stats([1,0,1])

    def test_award_once_per_attempt_even_if_replayed(self):
        store.migrate()
        writes = []
        def original_save(**kwargs):
            writes.append(kwargs)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('''INSERT INTO results(user_id,game_id,score,total_questions,correct_answers)
                              VALUES(?,?,?,?,?)''',
                           (kwargs['user_id'],kwargs['game_id'],kwargs['score'],
                            kwargs['total_questions'], kwargs['correct_answers']))
        data = dict(user_id=1,game_id=24,score=3,total_questions=5,correct_answers=3)
        with patch.object(store, '_request_metadata', return_value=('matching','token-test-123456789012345',3)):
            store.save_with_gamification(original_save, **data)
            store.save_with_gamification(original_save, **data)
        self.assertEqual(len(writes), 1)
        with closing(store.connect_db()) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM gamification_attempts WHERE status='completed'").fetchone()[0],2)
        p = store.progress_for_user(1)
        self.assertEqual(p['played'], 2)
        self.assertEqual(p['xp'], store.xp_for(4,5)+store.repeat_xp(store.xp_for(3,5,3)))
        self.assertEqual(p['best_streak'],3)
        self.assertTrue(next(a['unlocked'] for a in p['achievements'] if a['id']=='streak3'))

    def test_original_persistence_failure_clears_pending(self):
        store.migrate()
        data = dict(user_id=1,game_id=23,score=2,total_questions=4,correct_answers=2)
        with patch.object(store, '_request_metadata', return_value=('true_false','safe-token-123456789012345',1)):
            with self.assertRaises(RuntimeError):
                store.save_with_gamification(lambda **kw: (_ for _ in ()).throw(RuntimeError('db error')), **data)
            with closing(store.connect_db()) as db, db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM gamification_attempts WHERE status='pending'").fetchone()[0],0)
            calls=[]
            store.save_with_gamification(lambda **kw: calls.append(kw), **data)
            self.assertEqual(len(calls),1)

    def test_separate_users_do_not_share_progress(self):
        store.migrate()
        with patch.object(store,'_request_metadata',return_value=('classic','user-two-attempt-1234567890',1)):
            store.save_with_gamification(lambda **kw: None, user_id=2,game_id=23,
                                         score=1,total_questions=3,correct_answers=1)
        self.assertEqual(store.progress_for_user(2)['played'], 1)
        self.assertEqual(store.progress_for_user(1)['played'], 1)

if __name__=='__main__':
    unittest.main()
