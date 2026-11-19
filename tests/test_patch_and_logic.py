import ast
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
import install_true_false_mode as inst
import true_false_mode as tf


class TrueFalseQualityTests(unittest.TestCase):
    def test_saved_choices_and_keys(self):
        self.assertEqual(tf.to_saved_question({"statement": "Твердження номер один.", "is_true": True,
                                               "explanation": "Це справді правильний математичний факт."})["correct_answer"], "A")
        self.assertEqual(tf.to_saved_question({"statement": "Твердження номер два.", "is_true": False,
                                               "explanation": "Це не відповідає перевіреному факту."})["correct_answer"], "B")

    def test_disagreed_key_rejected(self):
        items = [
            {"statement": "Добуток двох і трьох дорівнює шести.", "is_true": True,
             "explanation": "Два помножити на три дорівнює шість."},
            {"statement": "Сума двох і трьох дорівнює семи.", "is_true": False,
             "explanation": "Насправді два плюс три дорівнює п'ять."},
        ]
        checks = {"checks": [{"index": 0, "valid": True, "is_true": False, "reason": ""},
                             {"index": 1, "valid": True, "is_true": False, "reason": ""}]}
        self.assertTrue(tf.validate_items(items, checks, 2))
        checks["checks"][0]["is_true"] = True
        self.assertEqual(tf.validate_items(items, checks, 2), [])

    def test_duplicate_invalid_missing_review_rejected(self):
        items = [{"statement": "Чотири помножити на п'ять дорівнює двадцять.",
                  "is_true": i % 2 == 0, "explanation": "Чотири помножити на п'ять дорівнює 20."} for i in range(2)]
        checks = {"checks": [{"index": i, "valid": True, "is_true": items[i]["is_true"], "reason": ""}
                             for i in range(2)]}
        self.assertTrue(tf.validate_items(items, checks, 2))
        self.assertTrue(tf.validate_items(items, {"checks": []}, 2))

    def test_failed_review_retries_and_no_persist(self):
        items = [{"statement": "Дванадцять ділиться на три без остачі.",
                  "is_true": True, "explanation": "Дванадцять ділити на три дорівнює чотири."},
                 {"statement": "Сім плюс три дорівнює п'ятнадцять.",
                  "is_true": False, "explanation": "Сім плюс три дорівнює десять."}]
        state = {"calls": 0}
        def draft(*args):
            state["calls"] += 1
            return {"items": items}
        def review(*args):
            return {"checks": [{"index": i, "valid": False, "is_true": x["is_true"], "reason": "test"}
                               for i, x in enumerate(items)]}
        with self.assertRaises(ValueError):
            tf.generate_truefalse_questions(subject="Math", topic="Arithmetic",
                difficulty="easy", question_count=2, generation_mode="openai",
                draft_fn=draft, review_fn=review)
        self.assertEqual(state["calls"], 2)

    def test_accepted_generation(self):
        items = [{"statement": "Три помножити на чотири дорівнює дванадцять.",
                  "is_true": True, "explanation": "Три помножити на чотири дорівнює дванадцять."},
                 {"statement": "Три помножити на чотири дорівнює тринадцять.",
                  "is_true": False, "explanation": "Три помножити на чотири дорівнює дванадцять."}]
        def review(items, subject):
            return {"checks": [{"index": i, "valid": True, "is_true": item["is_true"], "reason": ""}
                               for i, item in enumerate(items)]}
        result = tf.generate_truefalse_questions(subject="Math", topic="Numbers", difficulty="easy",
            question_count=2, generation_mode="openai",
            draft_fn=lambda *args: {"items": items}, review_fn=review)
        self.assertEqual([q["correct_answer"] for q in result], ["A", "B"])

    def test_demo_all_counts(self):
        for subj in ("Математика", "Українська мова", "Англійська мова"):
            for count in (1, 5, 10, 20):
                questions = tf.demo_questions(subj, count)
                self.assertEqual(len(questions), count)
                self.assertEqual(len({q['question_text'] for q in questions}), count)
                self.assertTrue(all(q['correct_answer'] in ('A','B') for q in questions))


class InstallerTests(unittest.TestCase):
    def test_installer_patch_known_integration(self):
        # Real baseline from previous InterOsvit updates, assembled in temp dir.
        # Does not require Flask; checks AST and Jinja syntax.
        from zipfile import ZipFile
        uploads = ROOT.parent
        if not all((uploads / x).exists() for x in (
            "app_updated.py", "install_app_changes_v2.py",
            "InterOsvit_Interactive_Stage_1_2.zip",
            "InterOsvit_Quiz_Fix_Selection.zip",
            "InterOsvit_Question_Accuracy_Fix.zip",
            "InterOsvit_Question_Editor.zip",
        )):
            self.skipTest("Цей тест вимагає вихідні архіви попередніх оновлень")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "templates").mkdir()
            app = (uploads / "app_updated.py").read_text(encoding="utf-8")
            (project / "app.py").write_text(app, encoding="utf-8")
            with ZipFile(uploads / "InterOsvit_Interactive_Stage_1_2.zip") as z:
                for name, dest in (("game_settings.py", project / "game_settings.py"),
                                   ("interactive_routes.py", project / "interactive_routes.py"),
                                   ("templates/create_game.html", project / "templates/create_game.html"),
                                   ("templates/interactive_game.html", project / "templates/interactive_game.html")):
                    archived = next(n for n in z.namelist() if n.endswith(name))
                    dest.write_bytes(z.read(archived))
            v2spec = importlib.util.spec_from_file_location("installv2", uploads / "install_app_changes_v2.py")
            v2 = importlib.util.module_from_spec(v2spec)
            v2spec.loader.exec_module(v2)
            with patch.object(v2, "APP", project / "app.py"), patch.object(v2, "ROOT", project):
                v2.main()
            with ZipFile(uploads / "InterOsvit_Question_Accuracy_Fix.zip") as z:
                src = z.read("install_question_quality.py").decode()
            quality = project / "install_question_quality.py"
            quality.write_text(src, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("installquality", quality)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main()
            # Editor blueprint registration doesn't affect route semantics.
            apptext = (project / "app.py").read_text()
            apptext = apptext.replace("app = Flask(__name__)",
                "app = Flask(__name__)\nfrom question_editor_routes import editor_bp\napp.register_blueprint(editor_bp)", 1)
            (project / "app.py").write_text(apptext)
            with ZipFile(uploads / "InterOsvit_Interactive_Stage_1_2.zip") as z:
                name = next(n for n in z.namelist() if n.endswith("game_settings.py"))
                (project / "game_settings.py").write_bytes(z.read(name))
                name = next(n for n in z.namelist() if n.endswith("create_game.html"))
                (project / "templates/create_game.html").write_bytes(z.read(name))
            with ZipFile(uploads / "InterOsvit_Quiz_Fix_Selection.zip") as z:
                for name, dest in (("interactive_routes.py", project / "interactive_routes.py"),
                                   ("templates/interactive_game.html", project / "templates/interactive_game.html")):
                    archived = next(n for n in z.namelist() if n.endswith(name))
                    dest.write_bytes(z.read(archived))
            with ZipFile(uploads / "InterOsvit_Question_Editor.zip") as z:
                for name, dest in (("question_editor_store.py", project / "question_editor_store.py"),
                                   ("templates/question_editor_form.html", project / "templates/question_editor_form.html")):
                    archived = next(n for n in z.namelist() if n.endswith(name))
                    dest.write_bytes(z.read(archived))
            (project / "true_false_mode.py").write_bytes((ROOT / "true_false_mode.py").read_bytes())
            changes = inst.changes_for_project(project)
            self.assertEqual(len(changes), 7)
            for path, (before, after) in changes.items():
                self.assertNotEqual(before, after)
                if path.suffix == ".py": compile(after, str(path), "exec")
            changed_app = changes[project / "app.py"][1]
            self.assertIn("generate_verified_questions", changed_app)
            self.assertIn("get_game_settings(game_id)['game_mode'] == 'true_false'", changed_app)
            self.assertIn("game_mode not in ('classic', 'interactive', 'true_false')", changed_app)
            self.assertIn("in ('interactive', 'true_false')", changed_app)
            self.assertIn("elif generation_mode == \"demo\"", changed_app)
            (project / "app.py").write_text(changed_app)
            for path, (_, after) in changes.items():
                if path.name != 'app.py': path.write_text(after)
            with self.assertRaises(ValueError):
                inst.changes_for_project(project)


if __name__ == "__main__": unittest.main()
