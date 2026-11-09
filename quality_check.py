from collections import Counter
import re


def normalize_text(value):
    """Нормалізація тексту для порівняння."""
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip()
    ).casefold()


def check_questions(questions, expected_count=None):
    """
    Перевіряє структуру навчальних запитань.

    Повертає:
    errors   - помилки, які потрібно виправити;
    warnings - можливі проблеми з якістю.
    """

    errors = []
    warnings = []

    if expected_count is not None:
        if len(questions) != expected_count:
            errors.append(
                f"Очікується {expected_count} запитань, "
                f"отримано {len(questions)}."
            )

    seen_questions = set()
    correct_answers = []

    for index, row in enumerate(questions, start=1):
        question = dict(row)

        prefix = f"Запитання {index}"

        text = normalize_text(
            question.get("question_text")
        )

        # Перевірка тексту запитання
        if not text:
            errors.append(
                f"{prefix}: відсутній текст запитання."
            )

        elif text in seen_questions:
            errors.append(
                f"{prefix}: запитання повторюється."
            )

        seen_questions.add(text)

        # Перевірка варіантів відповідей
        options = [
            normalize_text(question.get("option_a")),
            normalize_text(question.get("option_b")),
            normalize_text(question.get("option_c")),
            normalize_text(question.get("option_d"))
        ]

        if any(not option for option in options):
            errors.append(
                f"{prefix}: є порожній варіант відповіді."
            )

        elif len(set(options)) != 4:
            errors.append(
                f"{prefix}: варіанти відповідей повторюються."
            )

        # Перевірка правильної відповіді
        correct = question.get("correct_answer", "")

        if correct not in ("A", "B", "C", "D"):
            errors.append(
                f"{prefix}: неправильний формат correct_answer."
            )
        else:
            correct_answers.append(correct)

        # Перевірка пояснення
        explanation = str(
            question.get("explanation") or ""
        ).strip()

        if not explanation:
            errors.append(
                f"{prefix}: відсутнє пояснення."
            )

        elif len(explanation) < 25:
            warnings.append(
                f"{prefix}: пояснення може бути занадто коротким."
            )

    # Перевірка розподілу правильних відповідей
    if len(correct_answers) >= 5:
        counts = Counter(correct_answers)

        most_common_count = max(counts.values())

        if most_common_count / len(correct_answers) > 0.8:
            warnings.append(
                "Правильні відповіді надто часто "
                "мають одну й ту саму літеру."
            )

    return errors, warnings
