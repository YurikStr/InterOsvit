"""SQLite regression tests for true/false editor key locking, no Flask needed."""
from __future__ import annotations

import os
from contextlib import closing
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install_true_false_mode as inst
import true_false_mode as tf


class EditorTrueFalseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dbpath = Path(self.temp.name) / "interosvit.db"
        with closing(sqlite3.connect(self.dbpath)) as db:
            db.executescript("""
                CREATE TABLE games (id INTEGER PRIMARY KEY, user_id INTEGER,
                    title TEXT, subject TEXT, topic TEXT, share_token TEXT,
                    generation_status TEXT, deleted_at TEXT, game_mode TEXT);
                CREATE TABLE questions (id INTEGER PRIMARY KEY, game_id INTEGER,
                    question_text TEXT, option_a TEXT, option_b TEXT, option_c TEXT,
                    option_d TEXT, correct_answer TEXT, explanation TEXT);
                INSERT INTO games VALUES (1, 1, 'Test', 'Math', 'Add', 'abc',
                    'ready', NULL, 'true_false');
            """)
            db.execute("INSERT INTO questions VALUES (1,1,?,?,?,?,?,?,?)",
                ("Два плюс три дорівнює п'ять.",tf.A,tf.B,tf.C,tf.D,"A",
                 "Два плюс три насправді дорівнює п'ять."))
            db.commit()
        current_store = ROOT / 'question_editor_store.py'
        source_zip = ROOT.parent / 'InterOsvit_Question_Editor.zip'
        if current_store.is_file():
            raw = current_store.read_text(encoding='utf-8-sig')
            patched = raw if 'tuple(values[f"option_{letter}"]' in raw else inst.patch_store(raw)
        elif source_zip.is_file():
            with ZipFile(source_zip) as z:
                name = next(n for n in z.namelist() if n.endswith('question_editor_store.py'))
                raw = z.read(name).decode('utf-8')
            patched = inst.patch_store(raw)
        else:
            self.skipTest('Оригінальний редактор не знайдено')
        self.store = types.ModuleType("test_editor_store_tf")
        exec(compile(patched, "patched_store.py", "exec"), self.store.__dict__)
        self.env = patch.dict(os.environ, {"INTEROSVIT_DB_PATH": str(self.dbpath)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _form(self, correct):
        return dict(question_text="Два плюс три дорівнює п'ять.",
                    option_a=tf.A, option_b=tf.B, option_c=tf.C, option_d=tf.D,
                    correct_answer=correct,
                    explanation="Два плюс три насправді дорівнює п'ять.")

    def test_update_accepts_a_or_b_only(self):
        game, original = self.store.get_for_owner(1,1,1)
        version = self.store.fingerprint(original)
        self.store.update_for_owner(1,1,1,self._form("B"),version)
        _, changed = self.store.get_for_owner(1,1,1)
        self.assertEqual(changed["correct_answer"], "B")

    def test_rejects_fake_credits_and_wrong_owner(self):
        _, original = self.store.get_for_owner(1,1,1)
        version = self.store.fingerprint(original)
        with self.assertRaises(self.store.InvalidData):
            self.store.update_for_owner(1,1,1,self._form("C"), version)
        altered = self._form("A")
        altered["option_a"] = "Можливо"
        with self.assertRaises(self.store.InvalidData):
            self.store.update_for_owner(1,1,1,altered, version)
        with self.assertRaises(self.store.NotFound):
            self.store.update_for_owner(2,1,1,self._form("A"),version)
        _, unchanged = self.store.get_for_owner(1,1,1)
        self.assertEqual(unchanged["correct_answer"], "A")
        self.assertEqual(unchanged["option_a"], tf.A)


if __name__ == '__main__':
    unittest.main()
