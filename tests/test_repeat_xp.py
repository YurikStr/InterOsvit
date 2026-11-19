"""New repeat-play XP rules; isolated temporary SQLite databases only."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gamification_store as store


class RepeatXpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'interosvit.db'
        db = sqlite3.connect(self.path)
        try:
            db.executescript('''
              CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);
              CREATE TABLE games(id INTEGER PRIMARY KEY, game_mode TEXT);
              CREATE TABLE results(id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, game_id INTEGER, score INTEGER,
                total_questions INTEGER, correct_answers INTEGER,
                completed_at TEXT DEFAULT CURRENT_TIMESTAMP);
              INSERT INTO users(id,username) VALUES(1,'One'),(2,'Two');
              INSERT INTO games(id,game_mode) VALUES(24,'matching'),(23,'true_false');
            ''')
            db.commit()
        finally:
            db.close()
        self.path_patcher = patch.object(store, 'db_path', return_value=self.path)
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)
        self.addCleanup(self.temp.cleanup)
        store.migrate()

    def original_save(self, **kwargs):
        db = sqlite3.connect(self.path)
        try:
            db.execute('''INSERT INTO results (user_id,game_id,score,total_questions,correct_answers)
                            VALUES(?,?,?,?,?)''',
                       (kwargs['user_id'], kwargs['game_id'], kwargs['score'],
                        kwargs['total_questions'], kwargs['correct_answers']))
            db.commit()
        finally:
            db.close()

    def play(self, user, game, score, total, streak, token):
        with patch.object(store, '_request_metadata',
                          return_value=('matching' if game == 24 else 'true_false', token, streak)):
            return store.save_with_gamification(
                self.original_save,
                user_id=user, game_id=game, score=score,
                total_questions=total, correct_answers=score,
            )

    def rows(self, user, game):
        db = store.connect_db()
        try:
            return [dict(r) for r in db.execute('''SELECT * FROM gamification_attempts
                       WHERE user_id=? AND game_id=? ORDER BY rowid''', (user, game))]
        finally:
            db.close()

    def test_first_full_second_quarter_no_retroactive_change(self):
        self.play(1,24,4,5,3,'first-attempt-1234567890')
        first = self.rows(1,24)[0]['xp']
        self.assertEqual(first, store.xp_for(4,5,3))
        self.play(1,24,4,5,3,'second-attempt-1234567890')
        rows = self.rows(1,24)
        self.assertEqual([r['xp'] for r in rows], [first, store.repeat_xp(first)])
        self.assertEqual(store.progress_for_user(1)['xp'], first+store.repeat_xp(first))

    def test_58_xp_becomes_15_on_replay(self):
        self.assertEqual(store.xp_for(4,5,4), 58)
        self.assertEqual(store.repeat_xp(58), 15)
        self.assertEqual(store.repeat_xp(56), 14)
        self.assertEqual(store.repeat_xp(0), 0)
        with self.assertRaises(ValueError):
            store.repeat_xp(-1)

    def test_different_game_and_different_user_keep_full_xp(self):
        self.play(1,24,3,5,2,'one-game-24-token-123456')
        self.play(1,23,3,5,2,'one-game-23-token-123456')
        self.play(2,24,3,5,2,'two-game-24-token-123456')
        self.assertEqual(self.rows(1,24)[0]['xp'], store.xp_for(3,5,2))
        self.assertEqual(self.rows(1,23)[0]['xp'], store.xp_for(3,5,2))
        self.assertEqual(self.rows(2,24)[0]['xp'], store.xp_for(3,5,2))

    def test_same_token_retry_never_awards_again(self):
        token = 'same-attempt-123456789012345'
        self.play(1,24,5,5,5,token)
        self.play(1,24,5,5,5,token)
        self.assertEqual(len(self.rows(1,24)), 1)
        db = sqlite3.connect(self.path)
        try:
            count = db.execute('SELECT COUNT(*) FROM results WHERE user_id=1 AND game_id=24').fetchone()[0]
        finally:
            db.close()
        self.assertEqual(count, 1)

    def test_legacy_previous_completion_counts_as_first(self):
        # The migration imported prior completions, so a user replaying an old
        # completed game receives 25% rather than an extra 100%.
        db = sqlite3.connect(self.path)
        try:
            db.execute('''INSERT INTO gamification_attempts
                       (attempt_hash,user_id,game_id,mode,score,total,correct,
                        best_streak,xp,status,legacy)
                        VALUES('legacy:5',1,24,'matching',4,5,4,0,50,'completed',1)''')
            db.commit()
        finally:
            db.close()
        self.play(1,24,4,5,3,'replay-legacy-1234567890')
        self.assertEqual([row['xp'] for row in self.rows(1,24)],
                         [50, store.repeat_xp(store.xp_for(4,5,3))])

    def test_result_screen_uses_real_saved_award_when_flask_available(self):
        try:
            from flask import Flask, session
        except ImportError:
            self.skipTest('Flask доступний у робочому .venv InterOsvit')
        one = 'first-for-ui-12345678901234'
        two = 'replay-for-ui-1234567890123'
        self.play(1,24,4,5,4,one)
        self.play(1,24,4,5,4,two)
        app = Flask(__name__)
        app.secret_key = 'local-test-secret-123456789012345'
        app.add_url_rule('/match/demo', endpoint='matching.play_game', view_func=lambda: 'ok')
        with app.test_request_context('/match/demo'):
            session['user_id'] = 1
            session['io_matching_attempt_v1'] = {
                'game_id': 24, 'token': two, 'saved': True,
            }
            # Event sequence reflects four successful matching actions and
            # one intentional wrong action; the stored award is authoritative.
            earned = store.display_xp(4, 5, [True, False, True, True, True, True])
            self.assertEqual(earned, 15)

    def test_display_reads_confirmed_award(self):
        with patch.object(store, '_completed_attempt_xp_in_request', return_value=15):
            self.assertEqual(store.display_xp(4,5,[True,False,True,True,True]), 15)
        with patch.object(store, '_completed_attempt_xp_in_request', return_value=None):
            self.assertEqual(store.display_xp(4,5,[True,False,True,True,True]),
                             store.xp_for(4,5,3))


if __name__ == '__main__':
    unittest.main()
