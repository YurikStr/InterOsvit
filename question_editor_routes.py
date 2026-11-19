"""Author-only question editing, integrated as a standalone Flask Blueprint."""
from __future__ import annotations

import secrets
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session,
    url_for,
)
from question_editor_store import (
    Conflict, InvalidData, NotFound, fingerprint, get_for_owner,
    list_for_owner, update_for_owner,
)

editor_bp = Blueprint("question_editor", __name__)
_CSRF_KEY = "io_question_editor_csrf_v1"


def _logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        flash("Спочатку увійди до свого облікового запису")
        return None
    return int(user_id)


def _csrf() -> str:
    token = session.get(_CSRF_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def _owned_game_and_questions(user_id, game_id):
    try:
        return list_for_owner(user_id, game_id)
    except NotFound:
        abort(404)


@editor_bp.route("/games/<int:game_id>/questions", methods=["GET"])
def list_questions(game_id):
    user_id = _logged_in_user()
    if user_id is None:
        return redirect(url_for("login"))
    game, questions = _owned_game_and_questions(user_id, game_id)
    return render_template("question_editor_list.html", game=game,
                           questions=questions)


@editor_bp.route("/games/<int:game_id>/questions/<int:question_id>/edit",
                 methods=["GET", "POST"])
def edit_question(game_id, question_id):
    user_id = _logged_in_user()
    if user_id is None:
        return redirect(url_for("login"))
    try:
        game, question = get_for_owner(user_id, game_id, question_id)
    except NotFound:
        abort(404)

    if request.method == "POST":
        actual_csrf = request.form.get("editor_csrf", "")
        expected_csrf = session.get(_CSRF_KEY, "")
        if (not isinstance(expected_csrf, str) or not expected_csrf or
                not isinstance(actual_csrf, str) or
                not secrets.compare_digest(expected_csrf, actual_csrf)):
            abort(403, description="Недійсний захисний токен форми")
        submitted = {key: request.form.get(key, "") for key in
                     ("question_text", "option_a", "option_b", "option_c",
                      "option_d", "correct_answer", "explanation")}
        try:
            update_for_owner(user_id, game_id, question_id, submitted,
                             request.form.get("question_version", ""))
        except InvalidData as error:
            return render_template(
                "question_editor_form.html", game=game, question=question,
                values=submitted, version=fingerprint(question), csrf=_csrf(),
                error=str(error),
            ), 422
        except Conflict as error:
            # Re-fetch to show the latest version, never echo stale data as if saved.
            game, fresh_question = get_for_owner(user_id, game_id, question_id)
            return render_template(
                "question_editor_form.html", game=game, question=fresh_question,
                values=fresh_question, version=fingerprint(fresh_question),
                csrf=_csrf(), error=str(error),
            ), 409
        except NotFound:
            abort(404)
        flash("Запитання успішно збережено. Зміни вже доступні в грі")
        return redirect(url_for("question_editor.list_questions", game_id=game_id), code=303)

    return render_template(
        "question_editor_form.html", game=game, question=question,
        values=question, version=fingerprint(question), csrf=_csrf(), error=None,
    )
