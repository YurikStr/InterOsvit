"""Read-only independent audit for InterOsvit game_mode=true_false.

Separate from audit_existing_game.py, which was designed for 4-choice quizzes.
Requires OPENAI_API_KEY and OPENAI_MODEL/OPENAI_VALIDATION_MODEL in .env.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from true_false_mode import A, B, C, D, _review, validate_items

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')


def audit_game(game_id: int, *, review_fn=None) -> tuple[str, list[str], int]:
    path = Path(os.getenv('INTEROSVIT_DB_PATH') or ROOT / 'interosvit.db')
    if not path.is_file():
        raise ValueError(f'Не знайдено базу даних: {path}')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            'SELECT id, title, subject, game_mode FROM games '
            'WHERE id = ? AND deleted_at IS NULL', (game_id,),
        ).fetchone()
        if row is None:
            raise ValueError('Гру не знайдено або вона видалена')
        if row['game_mode'] != 'true_false':
            raise ValueError('Це не гра «Правда чи неправда». Для 4-варіантних ігор використовуй audit_existing_game.py')
        questions = db.execute(
            'SELECT question_text, option_a, option_b, option_c, option_d, '
            'correct_answer, explanation FROM questions WHERE game_id = ? ORDER BY id',
            (game_id,),
        ).fetchall()
        subject = row['subject']
        title = row['title']
    if not questions:
        raise ValueError('У грі немає запитань')
    if len(questions) > 20:
        raise ValueError('Занадто багато запитань для аудиту (максимум 20)')
    issues = []
    items = []
    for i, question in enumerate(questions, 1):
        if tuple(question[f'option_{letter}'] for letter in 'abcd') != (A, B, C, D):
            issues.append(f'Твердження {i}: нестандартні значення Правда/Неправда або службових варіантів')
        answer = question['correct_answer']
        if answer not in ('A', 'B'):
            issues.append(f'Твердження {i}: ключ має бути A або B')
        items.append({
            'statement': question['question_text'],
            'is_true': answer == 'A',
            'explanation': question['explanation'],
        })
    if issues:
        return title, issues, len(questions)
    reviewer = review_fn or _review
    review = reviewer(items, subject)
    return title, validate_items(items, review, len(items)), len(items)


def main():
    parser = argparse.ArgumentParser(description='Перевірити існуючу гру Правда/Неправда')
    parser.add_argument('--game-id', type=int, required=True)
    args = parser.parse_args()
    try:
        if args.game_id <= 0:
            raise ValueError('ID гри має бути додатним')
        title, issues, count = audit_game(args.game_id)
        print(f'Перевірено {count} тверджень: {title}')
        if issues:
            print('ВИЯВЛЕНО ПРОБЛЕМИ:')
            for issue in issues:
                print(' - ' + issue)
            print('Базу даних НЕ змінено. Не використовуй цю гру як перевірений матеріал.')
            raise SystemExit(2)
        print('Автоматична перевірка не виявила проблем. Потрібна також ручна перевірка.')
        print('Базу даних НЕ змінено.')
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'Помилка: {exc}\n')


if __name__ == '__main__':
    main()
