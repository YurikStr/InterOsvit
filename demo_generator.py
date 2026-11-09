
def generate_demo_questions(
    subject,
    topic,
    difficulty,
    question_count
):
    questions = []

    for number in range(1, question_count + 1):
        correct_number = number + 2

        question = {
            "question_text": (
                f"[ДЕМО] Запитання {number}. "
                f"Скільки буде {number} + 2?"
            ),
            "option_a": str(number),
            "option_b": str(number + 1),
            "option_c": str(correct_number),
            "option_d": str(number + 3),
            "correct_answer": "C",
            "explanation": (
                f"Це демонстраційне запитання. "
                f"{number} + 2 = {correct_number}."
            )
        }

        questions.append(question)

    return questions
