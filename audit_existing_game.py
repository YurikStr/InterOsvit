"""Read-only independent audit for ONE existing InterOsvit game. No UPDATEs."""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from verified_generation import review_questions_with_openai, verify_review


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Перевірити наявні запитання (тільки читання)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--game-id", type=int, help="ID гри для перевірки")
    group.add_argument("--list-games", action="store_true", help="Показати список ігор")
    args = parser.parse_args()
    path = Path(os.getenv("INTEROSVIT_DB_PATH") or Path(__file__).resolve().with_name("interosvit.db")).resolve()
    if not path.is_file():
        raise SystemExit(f"Базу даних не знайдено: {path}")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if args.list_games:
            for row in conn.execute("SELECT id, subject, title FROM games ORDER BY id DESC LIMIT 50"):
                print(f"ID={row['id']} | {row['subject']} | {row['title']}")
            return
        game = conn.execute("SELECT id, subject, title FROM games WHERE id = ?", (args.game_id,)).fetchone()
        if game is None:
            raise SystemExit("Гру з таким ID не знайдено")
        questions = [dict(x) for x in conn.execute(
            "SELECT question_text, option_a, option_b, option_c, option_d, correct_answer, explanation "
            "FROM questions WHERE game_id = ? ORDER BY id", (args.game_id,))]
    if not questions:
        print("У грі немає запитань для перевірки")
        return
    print(f"Перевіряємо {len(questions)} запитань: {game['title']}")
    review = review_questions_with_openai(questions, game['subject'])
    problems = verify_review(questions, review)
    if problems:
        print("ВИЯВЛЕНО ПРОБЛЕМИ:")
        for p in problems:
            print(" -", p)
        print("Дані в БД НЕ змінено. Не використовуй цю гру як перевірений навчальний матеріал.")
    else:
        print("Автоматична перевірка не виявила проблем, але це не гарантує повної правильності.")


if __name__ == "__main__":
    main()
