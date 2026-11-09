import argparse

from database import connect_db, get_game_questions
from quality_check import check_questions


def show_games():
    connection = connect_db()

    try:
        games = connection.execute(
            """
            SELECT
                games.id,
                games.title,
                games.subject,
                games.question_count,
                (
                    SELECT COUNT(*)
                    FROM questions
                    WHERE questions.game_id = games.id
                ) AS saved_questions
            FROM games
            WHERE games.deleted_at IS NULL
            ORDER BY games.id DESC
            """
        ).fetchall()

    finally:
        connection.close()

    print("\nДоступні ігри:\n")

    for game in games:
        print(
            f"ID: {game['id']} | "
            f"{game['title']} | "
            f"{game['subject']} | "
            f"{game['saved_questions']}/"
            f"{game['question_count']} запитань"
        )


def audit_game(game_id):
    connection = connect_db()

    try:
        game = connection.execute(
            """
            SELECT *
            FROM games
            WHERE id = ?
              AND deleted_at IS NULL
            """,
            (game_id,)
        ).fetchone()

    finally:
        connection.close()

    if game is None:
        print("Гру не знайдено.")
        return

    questions = get_game_questions(game_id)

    print(f"\nНазва гри: {game['title']}")
    print(f"Предмет: {game['subject']}")
    print(f"Тема: {game['topic']}")
    print(f"Складність: {game['difficulty']}")

    if not questions:
        print("\nУ цій грі ще немає запитань.")
        return

    print("\n--- НАВЧАЛЬНІ ЗАПИТАННЯ ---")

    for index, question in enumerate(questions, start=1):
        correct = question["correct_answer"]

        options = {
            "A": question["option_a"],
            "B": question["option_b"],
            "C": question["option_c"],
            "D": question["option_d"]
        }

        print(f"\n{index}. {question['question_text']}")

        for letter, text in options.items():
            print(f"   {letter}. {text}")

        print(
            f"Правильна відповідь: "
            f"{correct}. {options.get(correct, 'Невідома')}"
        )

        print(
            f"Пояснення: {question['explanation']}"
        )

    errors, warnings = check_questions(
        questions,
        expected_count=game["question_count"]
    )

    print("\n--- РЕЗУЛЬТАТ ПЕРЕВІРКИ ---")

    if errors:
        print("\nПомилки:")

        for error in errors:
            print(f"  - {error}")
    else:
        print("Структурних помилок не знайдено.")

    if warnings:
        print("\nПопередження:")

        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("Додаткових попереджень немає.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Перевірка якості запитань InterOsvit"
    )

    parser.add_argument(
        "game_id",
        type=int,
        nargs="?",
        help="ID гри для перевірки"
    )

    args = parser.parse_args()

    if args.game_id is None:
        show_games()
    else:
        audit_game(args.game_id)
