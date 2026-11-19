"""Idempotent SQLite migration. Run from the project root after a backup."""
import os
import sqlite3
from pathlib import Path


def main():
    db_path = Path(os.getenv("INTEROSVIT_DB_PATH") or Path(__file__).resolve().with_name("interosvit.db"))
    if not db_path.is_file():
        raise SystemExit(f"Базу не знайдено: {db_path}. Не створюємо порожню БД.")
    with sqlite3.connect(str(db_path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
        if not columns:
            raise SystemExit("Таблиця games не знайдена")
        if "game_mode" not in columns:
            conn.execute("ALTER TABLE games ADD COLUMN game_mode TEXT NOT NULL DEFAULT 'classic'")
            print("Додано games.game_mode (старі ігри: classic)")
        else:
            print("Колонка game_mode вже існує")
        if "custom_instructions" not in columns:
            conn.execute("ALTER TABLE games ADD COLUMN custom_instructions TEXT NOT NULL DEFAULT ''")
            print("Додано games.custom_instructions")
        else:
            print("Колонка custom_instructions вже існує")
        outcome = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if outcome != "ok":
            raise SystemExit(f"Перевірка цілісності БД: {outcome}")
    print("Міграція завершена. PRAGMA integrity_check: ok")


if __name__ == "__main__":
    main()
