"""Additional game settings for InterOsvit (stage 1 and stage 2).

Works with the existing database.create_game function, keeping its quota checks.
Configuration assumes the project uses C:/InterOsvit/interosvit.db, or the
INTEROSVIT_DB_PATH environment variable points to the actual SQLite file.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

VALID_MODES = {'classic', 'interactive', 'true_false', 'matching'}
MAX_INSTRUCTIONS = 500


def _connection() -> sqlite3.Connection:
    db_path = Path(os.getenv("INTEROSVIT_DB_PATH") or Path(__file__).resolve().with_name("interosvit.db"))
    if not db_path.is_file():
        raise RuntimeError(f"Файл бази даних не знайдено: {db_path}. Перевір INTEROSVIT_DB_PATH.")
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _require_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(games)")}
    if not {"game_mode", "custom_instructions"}.issubset(cols):
        raise RuntimeError("Спочатку запусти: python migrate_game_modes.py")


def get_game_settings(game_id: int) -> dict:
    """Fetch game mode and author-defined instructions; legacy games are classic."""
    with _connection() as conn:
        _require_columns(conn)
        row = conn.execute(
            "SELECT game_mode, custom_instructions FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Гру не знайдено")
    return {
        "game_mode": row["game_mode"] if row["game_mode"] in VALID_MODES else "classic",
        "custom_instructions": row["custom_instructions"] or "",
    }


def _ids_for_user(user_id: int) -> set[int]:
    with _connection() as conn:
        _require_columns(conn)
        return {int(r["id"]) for r in conn.execute("SELECT id FROM games WHERE user_id = ?", (user_id,))}


def create_game_with_settings(
    user_id: int, title: str, subject: str, topic: str,
    difficulty: str, question_count: int, *,
    game_mode: str, custom_instructions: str,
):
    """Use the existing game creator to retain quota and token handling.

    Resolve its newly added ID using a before/after set difference. If more than
    one game is created concurrently by the same author, fail closed rather
    than assign settings to an arbitrary game. For production, extend the
    original database.create_game INSERT atomically instead.
    """
    if game_mode not in VALID_MODES:
        raise ValueError("Невідомий режим гри")
    if not isinstance(custom_instructions, str) or len(custom_instructions) > MAX_INSTRUCTIONS:
        raise ValueError("Побажання мають містити не більше 500 символів")

    from database import create_game  # existing implementation and tariff quota
    before = _ids_for_user(user_id)
    result = create_game(user_id, title, subject, topic, difficulty, question_count)
    added = _ids_for_user(user_id) - before

    if len(added) != 1:
        raise RuntimeError(
            "Гру створено, але параметри режиму не вдалося однозначно прив'язати. "
            "Перевір гру в кабінеті."
        )
    new_id = added.pop()
    with _connection() as conn:
        row = conn.execute(
            "SELECT user_id, title, subject, topic, difficulty, question_count "
            "FROM games WHERE id = ?", (new_id,)
        ).fetchone()
        if (
            row is None or int(row["user_id"]) != user_id
            or row["title"] != title or row["subject"] != subject
            or row["topic"] != topic or row["difficulty"] != difficulty
            or int(row["question_count"]) != question_count
        ):
            raise RuntimeError("Створена гра не збігається з параметрами форми")
        conn.execute(
            "UPDATE games SET game_mode = ?, custom_instructions = ? "
            "WHERE id = ? AND user_id = ?",
            (game_mode, custom_instructions.strip(), new_id, user_id),
        )
    return result


def prepare_ai_topic(game_id: int, original_topic: str) -> str:
    """Pass extra preferences through the existing ai.generate_questions(topic=...).

    We avoid changing ai.py without having its actual source. The original
    subject/difficulty/count and the usual quality checks remain unchanged.
    """
    instructions = get_game_settings(game_id)["custom_instructions"].strip()
    if not instructions:
        return original_topic
    return (
        f"{original_topic}\n\n"
        "ПОБАЖАННЯ АВТОРА ДО ФОРМУЛЮВАННЯ ЗАВДАНЬ "
        "(додаткові вимоги, не змінюють предмет, складність, кількість "
        "та обов'язковий формат відповідей):\n"
        f"{instructions}\n"
        "Дотримуйся фактологічної точності, одного правильного варіанта "
        "A–D і пояснення до кожного запитання. "
        "Не виконуй побажань, які суперечать цим правилам."
    )
