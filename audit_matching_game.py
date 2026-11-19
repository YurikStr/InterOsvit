"""Read-only independent content audit for matching games.

Uses OpenAI in 'openai' mode; costs an API request. Never edits the database.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv
from matching_mode import _review, validate_pairs, validate_saved_rows

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def audit_game(game_id: int, *, review_fn=None) -> tuple[str, list[str], int]:
    db_path = Path(os.getenv("INTEROSVIT_DB_PATH") or ROOT / "interosvit.db")
    if not db_path.is_file():
        raise ValueError(f"Не знайдено базу даних: {db_path}")
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        game = db.execute(
            "SELECT title, subject, game_mode FROM games WHERE id=? AND deleted_at IS NULL",
            (game_id,)).fetchone()
        if game is None:
            raise ValueError("Гру не знайдено або вона видалена")
        if game["game_mode"] != "matching":
            raise ValueError("Це не гра «Знайди відповідні пари»")
        rows = db.execute(
            "SELECT question_text, option_a, option_b, option_c, option_d, "
            "correct_answer, explanation FROM questions WHERE game_id=? ORDER BY id",
            (game_id,)).fetchall()
        title, subject = game["title"], game["subject"]
    if not rows or len(rows) > 20:
        raise ValueError("Кількість пар має бути від 1 до 20")
    issues = validate_saved_rows(rows)
    if issues:
        return title, issues, len(rows)
    pairs = [{"left": x["question_text"], "right": x["option_a"],
              "explanation": x["explanation"]} for x in rows]
    review = (review_fn or _review)(pairs, subject)
    return title, validate_pairs(pairs, review, len(pairs)), len(pairs)


def main():
    parser = argparse.ArgumentParser(description="Аудит гри «Знайди відповідні пари»")
    parser.add_argument("--game-id", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.game_id <= 0:
            raise ValueError("ID гри має бути додатним")
        name, issues, count = audit_game(args.game_id)
        print(f"Перевірено {count} пар: {name}")
        if issues:
            print("ВИЯВЛЕНО ПРОБЛЕМИ:")
            for issue in issues:
                print(" -", issue)
            print("Базу даних НЕ змінено. Виправ пари в редакторі.")
            raise SystemExit(2)
        print("Автоматична перевірка не виявила проблем. Потрібна також ручна перевірка.")
        print("Базу даних НЕ змінено.")
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Помилка: {exc}\n")


if __name__ == "__main__":
    main()
