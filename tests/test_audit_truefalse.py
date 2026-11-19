"""Read-only audit verifies that correct keys and editor rules are enforced."""
import os
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import audit_truefalse_game as audit
import true_false_mode as tf


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'interosvit.db'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''
                CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, subject TEXT,
                    game_mode TEXT, deleted_at TEXT);
                CREATE TABLE questions (id INTEGER PRIMARY KEY, game_id INTEGER,
                    question_text TEXT, option_a TEXT, option_b TEXT,
                    option_c TEXT, option_d TEXT, correct_answer TEXT, explanation TEXT);
                INSERT INTO games VALUES (20, 'Демонстрація', 'Математика', 'true_false', NULL);
            ''')
            db.executemany('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?)', [
                (1,20, 'Добуток двох і трьох дорівнює шести.', tf.A, tf.B, tf.C,tf.D,'A',
                 'Два на три дорівнює шість, тому твердження правдиве.'),
                (2,20, 'Добуток двох і трьох дорівнює семи.', tf.A, tf.B, tf.C,tf.D,'B',
                 'Два на три дорівнює шість, а не сім, тому твердження неправдиве.'),
            ])
            db.commit()
        self.context = patch.dict(os.environ, {'INTEROSVIT_DB_PATH':str(self.path)})
        self.context.start()

    def tearDown(self):
        self.context.stop()
        self.tmp.cleanup()

    def test_audit_read_only_correct(self):
        checks = {'checks': [dict(index=i, valid=True, is_true=(i==0), reason='') for i in (0,1)]}
        title, problems, count = audit.audit_game(20,review_fn=lambda *args: checks)
        self.assertEqual((count, problems), (2, []))

    def test_detects_wrong_key(self):
        checks = {'checks': [dict(index=i, valid=True, is_true=False, reason='') for i in (0,1)]}
        _, problems, _ = audit.audit_game(20,review_fn=lambda *args: checks)
        self.assertTrue(problems)

    def test_rejects_four_option_game(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE games SET game_mode=? WHERE id=20', ('interactive',))
            db.commit()
        with self.assertRaises(ValueError):
            audit.audit_game(20,review_fn=lambda *args: None)


if __name__ == '__main__': unittest.main()
