"""Sanity checks on an installed InterOsvit project. Never edit files."""
import ast
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


class InstalledModeTests(unittest.TestCase):
    def test_installed_app_and_settings(self):
        app = PROJECT / 'app.py'
        if not app.exists():
            self.skipTest('Не інстальовано в корені проєкту')
        text = app.read_text(encoding='utf-8-sig')
        ast.parse(text)
        if 'generate_truefalse_questions' not in text:
            self.skipTest('Режим ще не інстальовано')
        self.assertIn("get_game_settings(game_id)['game_mode'] == 'true_false'", text)
        settings = PROJECT / 'game_settings.py'
        self.assertIn('true_false', settings.read_text(encoding='utf-8-sig'))
        self.assertIn('true_false', (PROJECT / 'interactive_routes.py').read_text(encoding='utf-8-sig'))
        self.assertIn('value="true_false"', (PROJECT / 'templates/create_game.html').read_text(encoding='utf-8-sig'))


if __name__ == '__main__': unittest.main()
