import os
import secrets

from dotenv import load_dotenv
from quality_check import check_questions
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from flask import Flask, render_template, request, redirect, url_for, flash, session
from database import (
    register_user,
    login_user,
    get_user_by_id,
    get_user_statistics,
    get_user_games,
    get_user_results,
    create_game,
    get_game_by_token,
    get_game_questions,
    get_game_owned_by_user,
    start_game_generation,
    set_game_generation_status,
    save_questions,
    get_user_game_quota,
    save_game_result,
    delete_user_game
)

load_dotenv()

app = Flask(__name__)
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

secret_key = os.getenv("SECRET_KEY")
if not secret_key or len(secret_key) < 32:
    raise RuntimeError("SECRET_KEY має містити щонайменше 32 символи.")

app.secret_key = secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=64 * 1024,
)

if IS_PRODUCTION:
    trusted_hosts = [
        host.strip()
        for host in os.getenv("TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ]
    if not trusted_hosts:
        raise RuntimeError("Для production налаштуй TRUSTED_HOSTS.")
    app.config["TRUSTED_HOSTS"] = trusted_hosts

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)


def generation_user_key():
    user_id = session.get("user_id")
    return f"user:{user_id}" if user_id is not None else f"ip:{get_remote_address()}"


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/")
def home():
    return render_template("index.html")



@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():

    if request.method == "POST":

        # 1. Перевірка CSRF-токена
        expected_token = session.get(
            "register_csrf_token", ""
        )

        submitted_token = request.form.get(
            "register_csrf_token", ""
        )

        if (
            not expected_token
            or not submitted_token
            or not secrets.compare_digest(
                expected_token,
                submitted_token
            )
        ):
            return (
                "Недійсний CSRF-токен. "
                "Оновіть сторінку та спробуйте ще раз.",
                400
            )

        # 2. Отримання даних форми
        username = request.form.get(
            "username", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        # 3. Перевірка обов'язкових полів
        if not username or not email or not password:
            flash("Заповніть усі поля!")
            return redirect(url_for("register"))

        # 4. Перевірка довжини пароля
        if len(password) < 8:
            flash(
                "Пароль повинен містити "
                "щонайменше 8 символів!"
            )
            return redirect(url_for("register"))

        # 5. Реєстрація користувача
        result = register_user(
            username,
            email,
            password
        )

        if result:

            # Видаляємо використаний CSRF-токен
            session.pop(
                "register_csrf_token",
                None
            )

            flash("Реєстрація успішна!")
            return redirect(url_for("login"))

        flash(
            "Користувач з таким ім'ям "
            "або email вже існує!"
        )

        return redirect(url_for("register"))

    # 6. Створення токена для GET-запиту
    csrf_token = session.get(
        "register_csrf_token"
    )

    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)

        session["register_csrf_token"] = (
            csrf_token
        )

    # 7. Відображення захищеної форми
    return render_template(
        "register.html",
        register_csrf_token=csrf_token
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():

    if request.method == "POST":

        # 1. Перевірка CSRF-токена
        expected_token = session.get(
            "login_csrf_token", ""
        )

        submitted_token = request.form.get(
            "login_csrf_token", ""
        )

        if (
            not expected_token
            or not submitted_token
            or not secrets.compare_digest(
                expected_token,
                submitted_token
            )
        ):
            return (
                "Недійсний CSRF-токен. "
                "Оновіть сторінку та спробуйте ще раз.",
                400
            )

        # 2. Отримання даних форми
        email = request.form.get(
            "email", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        # 3. Перевірка заповнення
        if not email or not password:
            flash("Заповніть усі поля!")
            return redirect(url_for("login"))

        # 4. Перевірка облікових даних
        user = login_user(email, password)

        if user:

            # Очищення попередніх даних сесії
            # перед створенням авторизованої сесії
            session.clear()

            # 5. Створення авторизованої сесії
            session["user_id"] = user["id"]
            session["username"] = user["username"]

            flash("Ви успішно увійшли!")

            return redirect(url_for("dashboard"))

        # 6. Невдалі облікові дані
        flash(
            "Неправильна електронна "
            "пошта або пароль!"
        )

        return redirect(url_for("login"))

    # 7. Отримання або створення CSRF-токена
    csrf_token = session.get("login_csrf_token")

    if not csrf_token:

        csrf_token = secrets.token_urlsafe(32)

        session["login_csrf_token"] = csrf_token

    # 8. Відображення захищеної форми
    return render_template(
        "login.html",
        login_csrf_token=csrf_token
    )

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Спочатку потрібно увійти в систему!")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Отримуємо інформацію про користувача
    user = get_user_by_id(user_id)

    if user is None:
        session.clear()
        flash("Користувача не знайдено. Увійдіть знову!")
        return redirect(url_for("login"))

    # Отримуємо загальну статистику
    statistics = get_user_statistics(user_id)

    # Отримуємо ігри, створені користувачем
    games = get_user_games(user_id)

    # Отримуємо тариф і залишок доступних створень
    quota = get_user_game_quota(user_id)

    # Обмеження історії відповідно до тарифу
    history_limit = 5 if quota["plan"] == "free" else None

    # Отримуємо історію проходження ігор
    results = get_user_results(
        user_id,
        limit=history_limit
    )

    # Перевіряємо, чи увімкнена генерація через OpenAI
    ai_enabled = (
        os.getenv("ENABLE_AI_GENERATION", "false").lower() == "true"
    )

    # Захисний токен для форми генерації запитань
    generate_csrf_token = session.get("generate_csrf_token")
    delete_csrf_token = session.get("delete_csrf_token")

    if not generate_csrf_token:
        generate_csrf_token = secrets.token_urlsafe(32)
        session["generate_csrf_token"] = generate_csrf_token
    if not delete_csrf_token:
        delete_csrf_token = secrets.token_urlsafe(32)
        session["delete_csrf_token"] = delete_csrf_token

    # Передаємо всі дані до HTML-шаблону
    return render_template(
    "dashboard.html",
    user=user,
    statistics=statistics,
    games=games,
    results=results,
    quota=quota,
    ai_enabled=ai_enabled,
    generate_csrf_token=generate_csrf_token,
    delete_csrf_token=delete_csrf_token
)



@app.route("/create_game", methods=["GET", "POST"])
def create_game_route():

    # 1. Перевірка авторизації
    if "user_id" not in session:
        flash("Спочатку потрібно увійти в систему!")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # 2. Обробка надсилання форми
    if request.method == "POST":

        # Перевірка CSRF-токена
        expected_token = session.get(
            "create_game_csrf_token", ""
        )

        submitted_token = request.form.get(
            "create_game_csrf_token", ""
        )

        if (
            not expected_token
            or not submitted_token
            or not secrets.compare_digest(
                expected_token,
                submitted_token
            )
        ):
            return (
                "Недійсний CSRF-токен. "
                "Оновіть сторінку та спробуйте ще раз.",
                400
            )

        # 3. Отримання даних форми
        title = request.form.get(
            "title", ""
        ).strip()

        subject = request.form.get(
            "subject", ""
        ).strip()

        topic = request.form.get(
            "topic", ""
        ).strip()

        difficulty = request.form.get(
            "difficulty", ""
        ).strip()

        question_count = request.form.get(
            "question_count", ""
        )

        # 4. Перевірка обов'язкових полів
        if (
            not title
            or not subject
            or not topic
            or not difficulty
        ):
            flash("Заповніть усі поля!")
            return redirect(
                url_for("create_game_route")
            )

        # 5. Перевірка кількості запитань
        try:
            question_count = int(question_count)

            if not 1 <= question_count <= 20:
                raise ValueError

        except (ValueError, TypeError):
            flash(
                "Кількість запитань повинна "
                "бути від 1 до 20!"
            )
            return redirect(
                url_for("create_game_route")
            )

        # 6. Створення гри
        # Перевірка тарифного ліміту
        # залишається в database.py
        try:
            create_game(
                user_id,
                title,
                subject,
                topic,
                difficulty,
                question_count
            )

        except ValueError as error:
            flash(str(error))
            return redirect(
                url_for("create_game_route")
            )

        # 7. Видаляємо використаний CSRF-токен
        # після успішного створення гри
        session.pop(
            "create_game_csrf_token",
            None
        )

        flash("Гру успішно створено!")
        return redirect(url_for("dashboard"))

    # 8. Перевірка тарифного ліміту
    # перед відображенням форми
    quota = get_user_game_quota(user_id)

    if quota is None:
        session.clear()
        flash(
            "Користувача не знайдено. "
            "Увійдіть знову!"
        )
        return redirect(url_for("login"))

    if quota["remaining"] <= 0:
        flash(
            "Ви використали місячний "
            "ліміт створення ігор!"
        )
        return redirect(url_for("dashboard"))

    # 9. Отримання або створення CSRF-токена
    csrf_token = session.get(
        "create_game_csrf_token"
    )

    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)

        session["create_game_csrf_token"] = (
            csrf_token
        )

    # 10. Відображення форми створення гри
    return render_template(
        "create_game.html",
        create_game_csrf_token=csrf_token
    )

@app.route("/game/<token>", methods=["GET", "POST"])
def game_page(token):
    game = get_game_by_token(token)

    if game is None:
        return "Гру не знайдено!", 404

    questions = get_game_questions(game["id"])
    attempt_key = f"attempt_{game['id']}"

    if request.method == "GET":
        # Новий токен для кожної спроби проходження
        attempt_token = secrets.token_urlsafe(16)
        session[attempt_key] = attempt_token

        return render_template(
            "game.html",
            game=game,
            questions=questions,
            result=None,
            attempt_token=attempt_token
        )

    # Перевіряємо, чи запит належить поточній спробі
    expected_token = session.get(attempt_key)
    submitted_token = request.form.get("attempt_token", "")

    if (
        not expected_token
        or not secrets.compare_digest(expected_token, submitted_token)
    ):
        flash("Спробу вже завершено. Почніть нову гру!")
        return redirect(url_for("game_page", token=token))

    if not questions:
        flash("У цій грі ще немає запитань.")
        return redirect(url_for("game_page", token=token))

    score = 0
    details = []

    for question in questions:
        answer = request.form.get(
            f"question_{question['id']}", ""
        ).strip().upper()

        if answer not in ("A", "B", "C", "D"):
            flash("Відповідайте на всі запитання!")
            return redirect(url_for("game_page", token=token))

        is_correct = answer == question["correct_answer"]

        if is_correct:
            score += 1

        details.append({
            "question": question["question_text"],
            "user_answer": answer,
            "correct_answer": question["correct_answer"],
            "is_correct": is_correct,
            "explanation": question["explanation"]
        })

    result = {
        "score": score,
        "total": len(questions),
        "percentage": round(score / len(questions) * 100),
        "details": details
    }

    result_saved = False

    # Зберігаємо результат лише авторизованого користувача
    if "user_id" in session:
        save_game_result(
            user_id=session["user_id"],
            game_id=game["id"],
            score=score,
            total_questions=len(questions),
            correct_answers=score
        )

        result_saved = True

    # Завершуємо спробу, щоб повторне надсилання
    # форми не створило ще один запис
    session.pop(attempt_key, None)

    return render_template(
        "game.html",
        game=game,
        questions=questions,
        result=result,
        result_saved=result_saved
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Ви успішно вийшли з облікового запису!")
    return redirect(url_for("login"))


@app.route("/games/<int:game_id>/generate", methods=["POST"])
@limiter.limit("5 per hour", key_func=generation_user_key)
@limiter.limit("20 per hour", key_func=get_remote_address)
def generate_game_questions_route(game_id):

    # 1. Перевірка авторизації
    if "user_id" not in session:
        flash("Спочатку увійдіть у систему!")
        return redirect(url_for("login"))

    # 2. Перевірка захисного токена форми
    expected_csrf = session.get("generate_csrf_token", "")
    submitted_csrf = request.form.get("generate_csrf_token", "")

    if (
        not expected_csrf
        or not submitted_csrf
        or not secrets.compare_digest(expected_csrf, submitted_csrf)
    ):
        return "Недійсний запит", 400

    # 3. Перевірка власника гри
    game = get_game_owned_by_user(
        game_id,
        session["user_id"]
    )

    if game is None:
        return "Гру не знайдено або доступ заборонено", 404

    # 4. Перевірка дозволу на генерацію
    ai_enabled = (
        os.getenv("ENABLE_AI_GENERATION", "false").lower() == "true"
    )

    if not ai_enabled:
        flash("Генерація запитань тимчасово вимкнена.")
        return redirect(url_for("dashboard"))

    # 5. Перевірка наявних запитань
    existing_questions = get_game_questions(game_id)

    if existing_questions:
        flash("Ця гра вже містить запитання!")
        return redirect(url_for("dashboard"))

    # 6. Визначення режиму генерації
    generation_mode = os.getenv(
        "AI_GENERATION_MODE", "demo"
    ).strip().lower()

    if generation_mode not in ("demo", "openai"):
        flash("Невідомий режим генерації.")
        return redirect(url_for("dashboard"))

    # Ключ потрібен лише для справжньої генерації
    if (
        generation_mode == "openai"
        and not os.getenv("OPENAI_API_KEY")
    ):
        flash("Ключ OpenAI API не налаштовано.")
        return redirect(url_for("dashboard"))

    # 7. Блокування повторної генерації
    if not start_game_generation(
        game_id,
        session["user_id"]
    ):
        flash(
            "Генерація вже виконується "
            "або гра недоступна для повторної генерації."
        )
        return redirect(url_for("dashboard"))

    try:
        # 8. Генерація запитань
        if generation_mode == "demo":

            from demo_generator import generate_demo_questions

            questions = generate_demo_questions(
                subject=game["subject"],
                topic=game["topic"] or "Загальна тема",
                difficulty=game["difficulty"],
                question_count=game["question_count"]
            )

        else:

            from ai import generate_questions

            questions = generate_questions(
                subject=game["subject"],
                topic=game["topic"] or "Загальна тема",
                difficulty=game["difficulty"],
                question_count=game["question_count"]
            )

        # 9. Перевірка кількості запитань
        if (
            not isinstance(questions, list)
            or len(questions) != game["question_count"]
        ):
            raise ValueError(
                "Неправильна кількість запитань"
            )

        # Обов'язкові поля запитання
        required_fields = (
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "correct_answer",
            "explanation"
        )

        # 10. Перевірка структури запитань
        for question in questions:

            if not isinstance(question, dict):
                raise ValueError(
                    "Некоректний формат запитання"
                )

            for field in required_fields:
                value = question.get(field)

                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Некоректне поле запитання: {field}"
                    )

            answer = question["correct_answer"].strip().upper()

            if answer not in ("A", "B", "C", "D"):
                raise ValueError(
                    "Некоректний варіант правильної відповіді"
                )

            question["correct_answer"] = answer

        # 11. Збереження запитань у SQLite
        # # Перевірка структури перед збереженням
        errors, warnings = check_questions(questions,expected_count=game["question_count"])
        if errors:
          raise ValueError(
        "Перевірка якості не пройдена: "
        + "; ".join(errors[:3]))
        # Попередження записуємо в лог
        for warning in warnings:
          app.logger.warning(
        "Гра %s: %s",
        game_id,
        warning)

        saved_count = save_questions(
            game_id,
            questions
        )

        if saved_count != game["question_count"]:
            raise ValueError(
                "Не вдалося зберегти всі запитання"
            )

        # 12. Позначаємо гру як готову
        set_game_generation_status(
            game_id,
            "ready"
        )

        flash("Запитання успішно згенеровано!")

    except Exception:

        app.logger.exception(
            "Помилка генерації для гри ID=%s",
            game_id
        )

        set_game_generation_status(
            game_id,
            "pending"
        )

        flash(
            "Не вдалося згенерувати запитання. "
            "Спробуйте пізніше."
        )

    return redirect(url_for("dashboard"))


@app.route("/games/<int:game_id>/delete", methods=["POST"])
def delete_game_route(game_id):

    if "user_id" not in session:
        flash("Спочатку увійдіть у систему!")
        return redirect(url_for("login"))

    # Перевірка захисного токена
    expected_token = session.get("delete_csrf_token", "")
    submitted_token = request.form.get(
        "delete_csrf_token", ""
    )

    if (
        not expected_token
        or not submitted_token
        or not secrets.compare_digest(
            expected_token,
            submitted_token
        )
    ):
        return "Недійсний запит", 400

    # Видаляємо лише власну гру
    deleted = delete_user_game(
        game_id,
        session["user_id"]
    )

    if deleted:
        flash(
            "Гру успішно видалено зі списку! "
        )
    else:
        flash(
            "Гру не знайдено, її вже видалено "
            "або зараз виконується генерація."
        )

    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    if IS_PRODUCTION:
        raise RuntimeError("Production запускай через WSGI-сервер.")
    app.run(host="127.0.0.1", port=5000, debug=True)
