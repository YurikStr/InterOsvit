"""Owner-scoped, transaction-safe editing of existing InterOsvit questions.

No schema migrations or API calls. The current SQLite schema is reused.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

QUESTION_FIELDS = (
    "question_text", "option_a", "option_b", "option_c", "option_d",
    "correct_answer", "explanation",
)
MAX_LENGTHS = {
    "question_text": 1500,
    "option_a": 300, "option_b": 300, "option_c": 300, "option_d": 300,
    "explanation": 2500,
}


class EditorError(Exception):
    """Base error for handling safe messages in the Flask route."""


class NotFound(EditorError):
    pass


class Conflict(EditorError):
    pass


class InvalidData(EditorError):
    pass


def open_db() -> sqlite3.Connection:
    path = Path(os.getenv("INTEROSVIT_DB_PATH") or
                Path(__file__).resolve().with_name("interosvit.db"))
    if not path.is_file():
        raise RuntimeError(f"Базу даних не знайдено: {path}")
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _game_for_owner(db, user_id: int, game_id: int) -> dict:
    row = db.execute(
        """SELECT id, user_id, title, subject, topic, share_token,
                  generation_status, game_mode FROM games
           WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
        (game_id, user_id),
    ).fetchone()
    if row is None:
        raise NotFound("Гру не знайдено або немає доступу")
    return dict(row)


def _question_in_game(db, game_id: int, question_id: int) -> dict:
    row = db.execute(
        """SELECT id, game_id, question_text, option_a, option_b, option_c,
                  option_d, correct_answer, explanation
           FROM questions WHERE id = ? AND game_id = ?""",
        (question_id, game_id),
    ).fetchone()
    if row is None:
        raise NotFound("Запитання не знайдено в цій грі")
    return dict(row)


def list_for_owner(user_id: int, game_id: int) -> tuple[dict, list[dict]]:
    db = open_db()
    try:
        game = _game_for_owner(db, user_id, game_id)
        rows = db.execute(
            """SELECT id, game_id, question_text, option_a, option_b,
                      option_c, option_d, correct_answer, explanation
               FROM questions WHERE game_id = ? ORDER BY id""", (game_id,)
        ).fetchall()
        return game, [dict(row) for row in rows]
    finally:
        db.close()


def get_for_owner(user_id: int, game_id: int, question_id: int) -> tuple[dict, dict]:
    db = open_db()
    try:
        game = _game_for_owner(db, user_id, game_id)
        question = _question_in_game(db, game_id, question_id)
        return game, question
    finally:
        db.close()


def fingerprint(question: dict) -> str:
    """Optimistic concurrency token based on persistent question contents."""
    serialized = json.dumps(
        [question.get("id"), question.get("game_id"),
         *[question.get(key) for key in QUESTION_FIELDS]],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_form(data) -> dict:
    cleaned = {}
    for name, limit in MAX_LENGTHS.items():
        value = data.get(name, "")
        if not isinstance(value, str):
            raise InvalidData("Некоректні дані форми")
        value = value.strip()
        if not value:
            raise InvalidData("Заповни текст запитання, всі варіанти та пояснення")
        if len(value) > limit:
            raise InvalidData(f"Поле «{name}» перевищує {limit} символів")
        if "\x00" in value:
            raise InvalidData("Текст містить недопустимий символ")
        cleaned[name] = value

    answer = str(data.get("correct_answer", "")).strip().upper()
    if answer not in {"A", "B", "C", "D"}:
        raise InvalidData("Обери правильну відповідь A, B, C або D")
    cleaned["correct_answer"] = answer

    normalized = [re.sub(r"\s+", " ", cleaned[f"option_{x}"].casefold())
                  for x in "abcd"]
    if len(set(normalized)) != 4:
        raise InvalidData("Усі чотири варіанти повинні відрізнятися")
    return cleaned


def update_for_owner(
    user_id: int, game_id: int, question_id: int,
    incoming, version: str,
) -> None:
    """Verify owner/question/version and update within a single write transaction."""
    values = validate_form(incoming)
    if not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", version):
        raise Conflict("Сторінка редагування застаріла. Онови її та спробуй ще раз")

    db = open_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        game = _game_for_owner(db, user_id, game_id)
        if game["game_mode"] == "matching":
            from matching_mode import B, C, D, normalize
            if (values["correct_answer"] != "A"
                    or tuple(values[f"option_{letter}"] for letter in "bcd") != (B, C, D)):
                raise InvalidData("Для гри з парами потрібно змінювати лише лівий та правий елементи")
            others = db.execute(
                "SELECT question_text, option_a FROM questions WHERE game_id = ? AND id != ?",
                (game_id, question_id),
            ).fetchall()
            left_key = normalize(values["question_text"])
            right_key = normalize(values["option_a"])
            if any(normalize(q["question_text"]) == left_key or
                   normalize(q["option_a"]) == right_key for q in others):
                raise InvalidData("Ліві та праві значення пар повинні бути унікальними")
        if game["game_mode"] == "true_false":
            from true_false_mode import A, B, C, D
            if (values["correct_answer"] not in ("A", "B")
                    or tuple(values[f"option_{letter}"] for letter in "abcd")
                    != (A, B, C, D)):
                raise InvalidData(
                    "Для гри «Правда чи неправда» дозволено лише "
                    "два незмінні варіанти: Правда і Неправда."
                )
        if game["generation_status"] == "generating":
            raise Conflict("Неможливо редагувати запитання під час генерації")
        current = _question_in_game(db, game_id, question_id)
        import secrets
        if not secrets.compare_digest(fingerprint(current), version):
            raise Conflict("Запитання вже змінено. Онови сторінку, щоб не перезаписати чужі зміни")

        cursor = db.execute(
            """UPDATE questions SET question_text = ?, option_a = ?,
                 option_b = ?, option_c = ?, option_d = ?, correct_answer = ?,
                 explanation = ? WHERE id = ? AND game_id = ?""",
            (values["question_text"], values["option_a"], values["option_b"],
             values["option_c"], values["option_d"], values["correct_answer"],
             values["explanation"], question_id, game_id),
        )
        if cursor.rowcount != 1:
            raise Conflict("Не вдалося зберегти запитання")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
