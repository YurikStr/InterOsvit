import secrets
import os
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
from contextlib import closing
from pathlib import Path
import sqlite3
from dotenv import load_dotenv

load_dotenv()
GAME_LIMITS = {
    "free": 5,
    "premium": 50
}

def connect_db():
    connection = sqlite3.connect("interosvit.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection

def create_users_table():
    connection = connect_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

def create_games_table():
    connection = connect_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            topic TEXT,
            difficulty TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

def add_user_id_to_games():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(games)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "user_id" not in column_names:
            connection.execute(
                """
                ALTER TABLE games
                ADD COLUMN user_id INTEGER REFERENCES users(id)
                """
            )

            connection.commit()
            print("Поле user_id успішно додано до таблиці games!")
        else:
            print("Поле user_id вже існує.")

    finally:
        connection.close()
def add_share_token_to_games():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(games)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "share_token" not in column_names:
            connection.execute(
                """
                ALTER TABLE games
                ADD COLUMN share_token TEXT
                """
            )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_games_share_token
                ON games(share_token)
                """
            )

            connection.commit()
            print("Поле share_token успішно додано!")

        else:
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_games_share_token
                ON games(share_token)
                """
            )

            print("Поле share_token вже існує.")

    finally:
        connection.close()
def fill_missing_share_tokens():
    connection = connect_db()

    try:
        games = connection.execute(
            """
            SELECT id
            FROM games
            WHERE share_token IS NULL
            """
        ).fetchall()

        for game in games:
            token = secrets.token_urlsafe(16)

            connection.execute(
                """
                UPDATE games
                SET share_token = ?
                WHERE id = ?
                """,
                (token, game["id"])
            )

        connection.commit()

        print(f"Токени створено для {len(games)} старих ігор!")

    finally:
        connection.close()
def add_question_count_to_games():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(games)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "question_count" not in column_names:
            connection.execute(
                """
                ALTER TABLE games
                ADD COLUMN question_count INTEGER NOT NULL DEFAULT 10
                """
            )

            connection.commit()
            print("Поле question_count успішно додано!")

        else:
            print("Поле question_count вже існує.")

    finally:
        connection.close()

def get_game_by_token(token):
    connection = connect_db()

    try:
        game = connection.execute(
            """
            SELECT *
            FROM games
            WHERE share_token = ?
              AND deleted_at IS NULL
            """,
            (token,)
        ).fetchone()

        return game

    finally:
        connection.close()

def create_questions_table():
    connection = connect_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            correct_answer TEXT NOT NULL,
            explanation TEXT,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    """)

    connection.commit()
    connection.close()

def create_results_table():
    connection = connect_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    """)

    connection.commit()
    connection.close()

def check_database():
    connection = connect_db()

    try:
        tables = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
        """).fetchall()

        print("Структура бази даних InterOsvit:")

        for table in tables:
            table_name = table["name"]

            print(f"\nТаблиця: {table_name}")

            columns = connection.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()

            for column in columns:
                print(
                    f"  Поле: {column['name']}, "
                    f"Тип: {column['type']}, "
                    f"Первинний ключ: {column['pk']}"
                )

        print("\nЗв'язки між таблицями:")

        for table in tables:
            table_name = table["name"]

            foreign_keys = connection.execute(
                f"PRAGMA foreign_key_list({table_name})"
            ).fetchall()

            for key in foreign_keys:
                print(
                    f"{table_name}.{key['from']} -> "
                    f"{key['table']}.{key['to']}"
                )

    finally:
        connection.close()
def check_database_integrity():
    connection = connect_db()

    try:
        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        print("Перевірка цілісності бази даних:")
        print(result[0])

    finally:
        connection.close()

def register_user(username, email, password):
    connection = connect_db()

    try:
        password_hash = generate_password_hash(password)

        connection.execute("""
            INSERT INTO users (username, email, password)
            VALUES (?, ?, ?)
        """, (username, email, password_hash))

        connection.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        connection.close()

def login_user(email, password):
    connection = connect_db()

    try:
        user = connection.execute("""
            SELECT * FROM users
            WHERE email = ?
        """, (email,)).fetchone()

        if user and check_password_hash(user["password"], password):
            return user

        return None

    finally:
        connection.close()
def get_user_by_id(user_id):
    connection = connect_db()

    try:
        user = connection.execute(
            """
            SELECT id, username, email, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        return user

    finally:
        connection.close()
def get_user_statistics(user_id):
    connection = connect_db()

    try:
        statistics = connection.execute(
            """
            SELECT
                COUNT(*) AS games_played,
                COALESCE(SUM(score), 0) AS total_score,
                COALESCE(SUM(correct_answers), 0) AS correct_answers,
                COALESCE(SUM(total_questions), 0) AS total_questions
            FROM results
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        return statistics

    finally:
        connection.close()


def create_game(
    user_id,
    title,
    subject,
    topic,
    difficulty,
    question_count
):
    connection = connect_db()

    try:
        # Захист від одночасного створення ігор
        connection.execute("BEGIN IMMEDIATE")

        user = connection.execute(
            """
            SELECT plan
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        if user is None:
            raise ValueError("Користувача не знайдено.")

        plan = user["plan"]

        # Враховуємо тестові привілеї розробника
        monthly_limit = get_effective_game_limit(
            user_id,
            plan
        )

        row = connection.execute(
            """
            SELECT COUNT(*) AS created_games
            FROM games
            WHERE user_id = ?
              AND created_at >= datetime(
                  'now', 'start of month'
              )
              AND created_at < datetime(
                  'now', 'start of month', '+1 month'
              )
            """,
            (user_id,)
        ).fetchone()

        used = row["created_games"]

        # Перевірка місячного ліміту
        if used >= monthly_limit:
            raise ValueError(
                "Ви використали місячний ліміт "
                "створення ігор. "
                "Наступного місяця ліміт оновиться."
            )

        # Унікальний токен гри
        share_token = secrets.token_urlsafe(16)

        cursor = connection.execute(
            """
            INSERT INTO games (
                user_id,
                title,
                subject,
                topic,
                difficulty,
                share_token,
                question_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                title,
                subject,
                topic,
                difficulty,
                share_token,
                question_count
            )
        )

        connection.commit()

        return cursor.lastrowid

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def get_user_games(user_id):
    connection = connect_db()

    try:
        games = connection.execute(
            """
            SELECT
                games.*,
                COUNT(questions.id) AS saved_questions
            FROM games
            LEFT JOIN questions
                ON questions.game_id = games.id
            WHERE games.user_id = ?
              AND games.deleted_at IS NULL
            GROUP BY games.id
            ORDER BY
                games.created_at DESC,
                games.id DESC
            """,
            (user_id,)
        ).fetchall()

        return games

    finally:
        connection.close()


def test_game_owner():
    connection = connect_db()

    try:
        games = connection.execute(
            """
            SELECT id, title, user_id, share_token
            FROM games
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

        for game in games:
            print(
                f"ID: {game['id']}, "
                f"Назва: {game['title']}, "
                f"Автор: {game['user_id']}, "
                f"Токен: {game['share_token']}"
            )

    finally:
        connection.close()
def save_questions(game_id, questions):
    connection = connect_db()

    try:
        existing = connection.execute(
            "SELECT COUNT(*) FROM questions WHERE game_id = ?",
            (game_id,)
        ).fetchone()[0]

        if existing > 0:
            return 0

        for question in questions:
            if question["correct_answer"] not in ("A", "B", "C", "D"):
                raise ValueError("Некоректна правильна відповідь")

            connection.execute(
                """
                INSERT INTO questions (
                    game_id,
                    question_text,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_answer,
                    explanation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    question["question_text"],
                    question["option_a"],
                    question["option_b"],
                    question["option_c"],
                    question["option_d"],
                    question["correct_answer"],
                    question["explanation"]
                )
            )

        connection.commit()
        return len(questions)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_game_questions(game_id):
    connection = connect_db()

    try:
        questions = connection.execute(
            """
            SELECT *
            FROM questions
            WHERE game_id = ?
            ORDER BY id
            """,
            (game_id,)
        ).fetchall()

        return questions

    finally:
        connection.close()

def save_game_result(user_id, game_id, score, total_questions, correct_answers):
    connection = connect_db()

    try:
        cursor = connection.execute(
            """
            INSERT INTO results (
                user_id,
                game_id,
                score,
                total_questions,
                correct_answers
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                game_id,
                score,
                total_questions,
                correct_answers
            )
        )

        connection.commit()
        return cursor.lastrowid

    except sqlite3.Error:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_user_results(user_id, limit=None):
    connection = connect_db()

    try:
        query = """
            SELECT
                results.id,
                games.title AS game_title,
                games.subject,
                games.topic,
                games.share_token,
                results.score,
                results.total_questions,
                results.correct_answers,
                results.completed_at
            FROM results
            JOIN games
                ON results.game_id = games.id
            WHERE results.user_id = ?
            ORDER BY
                results.completed_at DESC,
                results.id DESC
        """

        parameters = [user_id]

        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        return connection.execute(
            query,
            parameters
        ).fetchall()

    finally:
        connection.close()

def add_generation_status_to_games():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(games)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "generation_status" not in column_names:
            connection.execute(
                """
                ALTER TABLE games
                ADD COLUMN generation_status TEXT
                NOT NULL DEFAULT 'pending'
                """
            )

            print("Поле generation_status успішно додано!")

        # Позначаємо вже заповнені ігри як готові.
        connection.execute(
            """
            UPDATE games
            SET generation_status = 'ready'
            WHERE question_count > 0
              AND (
                  SELECT COUNT(*)
                  FROM questions
                  WHERE questions.game_id = games.id
              ) >= games.question_count
              AND generation_status = 'pending'
            """
        )

        connection.commit()

    finally:
        connection.close()

def get_game_owned_by_user(game_id, user_id):
    connection = connect_db()

    try:
        return connection.execute(
            """
            SELECT *
            FROM games
           WHERE id = ?
           AND user_id = ?
           AND deleted_at IS NULL
            """,
            (game_id, user_id)
        ).fetchone()

    finally:
        connection.close()


def start_game_generation(game_id, user_id):
    connection = connect_db()

    try:
        cursor = connection.execute(
            """
            UPDATE games
            SET generation_status = 'generating'
            WHERE id = ?
              AND user_id = ?
              AND generation_status = 'pending'
              AND NOT EXISTS (
                  SELECT 1
                  FROM questions
                  WHERE questions.game_id = games.id
              )
            """,
            (game_id, user_id)
        )

        connection.commit()

        return cursor.rowcount == 1

    finally:
        connection.close()


def set_game_generation_status(game_id, status):
    allowed_statuses = ("pending", "ready")

    if status not in allowed_statuses:
        raise ValueError("Невідомий статус генерації")

    connection = connect_db()

    try:
        connection.execute(
            """
            UPDATE games
            SET generation_status = ?
            WHERE id = ?
              AND generation_status = 'generating'
            """,
            (status, game_id)
        )

        connection.commit()

    finally:
        connection.close()

def add_user_plan_to_users():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(users)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "plan" not in column_names:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN plan TEXT NOT NULL
                DEFAULT 'free'
                CHECK (plan IN ('free', 'premium'))
                """
            )

            connection.commit()
            print("Поле plan успішно додано!")
        else:
            print("Поле plan вже існує.")

    finally:
        connection.close()
def is_test_developer(user_id):
    """Перевіряє, чи має користувач тестові привілеї."""

    if os.getenv("APP_ENV") != "development":
        return False

    if os.getenv("ENABLE_DEV_QUOTA", "false").lower() != "true":
        return False

    developer_id = os.getenv("DEV_USER_ID", "")

    if not developer_id.isdigit():
        return False

    return int(developer_id) == int(user_id)


def get_effective_game_limit(user_id, plan):
    """Повертає місячний ліміт відповідно до тарифу та режиму."""

    if is_test_developer(user_id):
        return 1_000_000

    return GAME_LIMITS.get(plan, 5)
def get_user_game_quota(user_id):
    connection = connect_db()

    try:
        user = connection.execute(
            """
            SELECT plan
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        if user is None:
            return None

        plan = user["plan"]

        # Звичайний або тестовий ліміт
        monthly_limit = get_effective_game_limit(
            user_id,
            plan
        )

        row = connection.execute(
            """
            SELECT COUNT(*) AS created_games
            FROM games
            WHERE user_id = ?
              AND created_at >= datetime(
                  'now', 'start of month'
              )
              AND created_at < datetime(
                  'now', 'start of month', '+1 month'
              )
            """,
            (user_id,)
        ).fetchone()

        used = row["created_games"]
        remaining = max(0, monthly_limit - used)

        return {
            "plan": plan,
            "limit": monthly_limit,
            "used": used,
            "remaining": remaining
        }

    finally:
        connection.close()

def delete_user_game(game_id, user_id):
    connection = connect_db()

    try:
        cursor = connection.execute(
            """
            UPDATE games
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
              AND deleted_at IS NULL
              AND generation_status != 'generating'
            """,
            (game_id, user_id)
        )

        connection.commit()

        return cursor.rowcount == 1

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def add_deleted_at_to_games():
    connection = connect_db()

    try:
        columns = connection.execute(
            "PRAGMA table_info(games)"
        ).fetchall()

        column_names = [
            column["name"] for column in columns
        ]

        if "deleted_at" not in column_names:
            connection.execute(
                """
                ALTER TABLE games
                ADD COLUMN deleted_at TIMESTAMP
                """
            )

            connection.commit()
            print("Поле deleted_at успішно додано!")
        else:
            print("Поле deleted_at вже існує.")

    finally:
        connection.close()
def set_user_plan(user_id, plan):
    """Змінює тариф конкретного користувача. Повертає True при успіху."""
    if plan not in ("free", "premium"):
        raise ValueError("Невідомий тарифний план")

    db_path = Path(__file__).resolve().parent / "interosvit.db"
    # Якщо у database.py БД налаштована іншим шляхом, використай той самий шлях тут.
    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            cursor = connection.execute(
                "UPDATE users SET plan = ? WHERE id = ?",
                (plan, user_id),
            )
            return cursor.rowcount > 0
def is_test_developer(user_id):
    """Дозволяє розширену квоту лише розробнику локально."""
    return (
        os.getenv("APP_ENV") == "development"
        and os.getenv("ENABLE_DEV_QUOTA", "false").lower() == "true"
        and os.getenv("DEV_USER_ID", "").isdigit()
        and int(os.getenv("DEV_USER_ID")) == int(user_id)
    )
if __name__ == "__main__":
    test_game_owner()
if __name__ == "__main__":
    create_users_table()
    create_games_table()
    add_user_id_to_games()
    add_share_token_to_games()
    fill_missing_share_tokens()
    add_question_count_to_games()

    check_database()
    check_database_integrity()
    test_game_owner()


# INTEROSVIT_GAMIFICATION_WRAPPER_V1
_io_original_save_game_result_v1 = save_game_result

def save_game_result(*args, **kwargs):
    """Persist one attempt and award XP; avoid duplicate replay."""
    from gamification_store import save_with_gamification
    return save_with_gamification(_io_original_save_game_result_v1, *args, **kwargs)
