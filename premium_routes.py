import os
import secrets

from flask import (
    Blueprint, abort, flash, redirect, render_template, request,
    session, url_for,
)

from database import get_user_by_id, set_user_plan, get_user_game_quota

premium_bp = Blueprint("premium", __name__)


def demo_premium_enabled():
    """Дозволяє зміну тарифу лише для локальної розробки."""
    return (
        os.getenv("APP_ENV", "development").strip().lower() == "development"
        and os.getenv("ENABLE_DEMO_PREMIUM", "false").strip().lower() == "true"
        and request.remote_addr in {"127.0.0.1", "::1"}
    )

@premium_bp.get("/pricing")
def pricing():
    """Показує тарифи; форма демоактивації з'являється лише локально."""
    user_id = session.get("user_id")
    user = get_user_by_id(user_id) if user_id is not None else None

    if user_id is not None and user is None:
        session.clear()
        flash("Сесію завершено. Увійдіть ще раз.")
        return redirect(url_for("login"))

    csrf_token = session.get("premium_csrf_token")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session["premium_csrf_token"] = csrf_token

    quota = get_user_game_quota(user_id) if user is not None else None

    return render_template(
        "pricing.html",
        logged_in=user is not None,
        current_plan=quota["plan"] if quota is not None else None,
        demo_enabled=demo_premium_enabled(),
        premium_csrf_token=csrf_token,
    )


@premium_bp.post("/premium/demo-change-plan")
def demo_change_plan():
    """Вмикає Premium або повертає Free тільки для локальних тестів."""
    user_id = session.get("user_id")
    if user_id is None:
        flash("Спочатку увійдіть в обліковий запис.")
        return redirect(url_for("login"))

    # Важливо: навіть прямий POST на опублікованому сайті не змінить тариф.
    if not demo_premium_enabled():
        abort(404)

    expected = session.get("premium_csrf_token")
    received = request.form.get("premium_csrf_token", "")
    if not expected or not secrets.compare_digest(expected, received):
        abort(400, description="Недійсний CSRF-токен")

    new_plan = request.form.get("plan", "").strip().lower()
    if new_plan not in {"free", "premium"}:
        abort(400, description="Невідомий тариф")

    if get_user_by_id(user_id) is None:
        session.clear()
        flash("Користувача не знайдено.")
        return redirect(url_for("login"))

    if not set_user_plan(user_id, new_plan):
        abort(404)

    # Одноразовий CSRF-токен: повторно надсилати ту саму форму не можна.
    session.pop("premium_csrf_token", None)

    if new_plan == "premium":
        flash("Premium активовано в демонстраційному режимі. Оплата не стягувалася.")
    else:
        flash("Для тестування відновлено тариф Free.")
    return redirect(url_for("dashboard"))
