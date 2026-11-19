import ast
import sys
import unittest
from pathlib import Path
from jinja2 import Environment

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import install_gamification as installer

class InstallationTests(unittest.TestCase):
    def test_files_compilable_and_templates_valid(self):
        for f in ROOT.glob('*.py'): ast.parse(f.read_text(encoding='utf-8'))
        for f in (ROOT/'templates').glob('*.html'): Environment().parse(f.read_text(encoding='utf-8'))
    def test_database_wrapper_safe_reinstall(self):
        raw='def save_game_result(user_id,game_id,score,total_questions,correct_answers):\n    pass\n'
        changed=installer.patch_database(raw)
        ast.parse(changed)
        self.assertIn('_io_original_save_game_result_v1',changed)
        with self.assertRaises(ValueError): installer.patch_database(changed)
    def test_route_context_patches(self):
        base=ROOT.parent/'InterOsvit_Matching_Mode_v1'
        if not base.is_dir():
            self.skipTest('Previous mode files unavailable; run on development machine')
        src=(base/'matching_routes.py').read_text(encoding='utf-8')
        changed=installer.patch_matching_route(src)
        ast.parse(changed)
        self.assertIn('state["events"].append(left == right)', changed)
        with self.assertRaises(ValueError): installer.patch_matching_route(changed)
        html=(base/'templates/matching_game.html').read_text(encoding='utf-8')
        Environment().parse(installer.patch_matching_html(html))

if __name__=='__main__': unittest.main()
