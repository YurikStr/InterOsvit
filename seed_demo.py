from database import (
    connect_db,
    create_game,
    save_questions,
    get_user_by_id
)

USER_ID = 2
TITLE = "Демогра: Основи Python"

if get_user_by_id(USER_ID) is None:
    raise SystemExit("Користувача з таким ID не знайдено!")

connection = connect_db()

try:
    existing_game = connection.execute(
        """
        SELECT id, share_token
        FROM games
        WHERE user_id = ? AND title = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (USER_ID, TITLE)
    ).fetchone()
finally:
    connection.close()

if existing_game:
    game_id = existing_game["id"]
    token = existing_game["share_token"]
else:
    game_id = create_game(
        USER_ID,
        TITLE,
        "Інформатика",
        "Основи Python",
        "Легка",
        5
    )

    connection = connect_db()
    try:
        game = connection.execute(
            "SELECT share_token FROM games WHERE id = ?",
            (game_id,)
        ).fetchone()
        token = game["share_token"]
    finally:
        connection.close()


questions = [
    {
        "question_text": "Яка функція виводить текст у консоль Python?",
        "option_a": "print()",
        "option_b": "input()",
        "option_c": "len()",
        "option_d": "range()",
        "correct_answer": "A",
        "explanation": "Функція print() виводить інформацію в консоль."
    },
    {
        "question_text": "Який тип даних має значення True?",
        "option_a": "str",
        "option_b": "bool",
        "option_c": "int",
        "option_d": "list",
        "correct_answer": "B",
        "explanation": "bool — логічний тип даних із значеннями True та False."
    },
    {
        "question_text": "Що поверне len([10, 20, 30])?",
        "option_a": "2",
        "option_b": "4",
        "option_c": "3",
        "option_d": "30",
        "correct_answer": "C",
        "explanation": "Функція len() повертає кількість елементів списку."
    },
    {
        "question_text": "Який символ використовується для коментаря в Python?",
        "option_a": "//",
        "option_b": "<!--",
        "option_c": "/*",
        "option_d": "#",
        "correct_answer": "D",
        "explanation": "У Python однорядковий коментар починається символом #."
    },
    {
        "question_text": "Який оператор перевіряє рівність двох значень?",
        "option_a": "=",
        "option_b": "==",
        "option_c": "!=",
        "option_d": ">=",
        "correct_answer": "B",
        "explanation": "Оператор == порівнює два значення, а = використовується для присвоєння."
    }
]

saved = save_questions(game_id, questions)

print(f"Додано запитань: {saved}")
print(f"ID гри: {game_id}")
print(f"Посилання: http://127.0.0.1:5000/game/{token}")
