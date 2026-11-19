from ai import generate_questions

questions = generate_questions(
    subject="Математика",
    topic="Квадратні рівняння",
    difficulty="Середній",
    question_count=3
)

if questions:
    for index, question in enumerate(questions, start=1):
        print(f"\nЗапитання {index}:")
        print(question["question_text"])

        print("A:", question["option_a"])
        print("B:", question["option_b"])
        print("C:", question["option_c"])
        print("D:", question["option_d"])

        print("Правильна відповідь:", question["correct_answer"])
        print("Пояснення:", question["explanation"])
else:
    print("Не вдалося згенерувати запитання.")