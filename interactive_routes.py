"""Server-checked step-by-step quiz, no answers/keys embedded in initial HTML.

This is a local-project MVP: attempt state uses Flask's signed cookie session.
For public deployment, move attempts to a server-side store with unique
completion tokens for durable replay protection.
"""
from __future__ import annotations

import secrets
import re
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from database import get_game_by_token, get_game_questions, save_game_result
from game_settings import get_game_settings

interactive_bp = Blueprint("interactive", __name__)
_STATE_KEY = "io_interactive_attempt_v1"
_LETTERS = {"A", "B", "C", "D"}


# Назви варіантів беремо з БД, а не з тексту, згенерованого ШІ.
def _option_text(question, letter: str) -> str:
    if letter not in _LETTERS:
        return ""
    return str(question[f"option_{letter.lower()}"])


def _clean_explanation(raw: str) -> str:
    """Забирає кінцеву вказівку літери з пояснення ШІ.

    Напр.: «96 − 60 = 36. Правильна відповідь — B.» -> «96 − 60 = 36.»
    Показану користувачеві правильну літеру визначає correct_answer із БД.
    Це не є перевіркою фактичної правильності математичних пояснень.
    """
    text = str(raw or "").strip()
    pattern = (
        r"\s*(?:Отже,?\s*)?"
        r"(?:Правильна\s+відповідь|Правильний\s+варіант)"
        r"\s*(?:[:—–-]\s*|це\s+)?"
        r"(?:варіант\s*)?[A-D]\s*[.!]?\s*$"
    )
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


def _new_attempt(game_id: int, questions) -> dict:
    return {
        "game_id": game_id,
        "question_ids": [int(q["id"]) for q in questions],
        "token": secrets.token_urlsafe(24),
        "answers": [],
        "phase": "question",
        "saved": False,
    }


def _result(questions, answers):
    details = []
    for q, answer in zip(questions, answers):
        correct = q["correct_answer"].strip().upper()
        details.append({
            "question": q["question_text"],
            "user_answer": answer,
            "user_answer_text": _option_text(q, answer),
            "correct_answer": correct,
            "correct_answer_text": _option_text(q, correct),
            "is_correct": answer == correct,
            "explanation": _clean_explanation(q["explanation"]),
        })
    score = sum(1 for item in details if item["is_correct"])
    total = len(questions)
    return {"score": score, "total": total,
            "percentage": round(score / total * 100) if total else 0,
            "details": details}


@interactive_bp.route("/play/<token>", methods=["GET", "POST"])
def play_game(token):
    game = get_game_by_token(token)
    if game is None:
        abort(404)
    mode = get_game_settings(game["id"])["game_mode"]
    if mode not in ("interactive", "true_false"):
        return redirect(url_for("game_page", token=token))

    questions = get_game_questions(game["id"])
    if not questions:
        return render_template("interactive_game.html", game=game, total=0,
                               phase="empty", is_true_false=(mode == "true_false"))

    expected_ids = [int(q["id"]) for q in questions]
    state = session.get(_STATE_KEY)
    if (not isinstance(state, dict)
            or state.get("game_id") != game["id"]
            or state.get("question_ids") != expected_ids
            or not isinstance(state.get("answers"), list)
            or len(state["answers"]) > len(questions)
            or state.get("phase") not in {"question", "feedback", "complete"}):
        state = _new_attempt(game["id"], questions)
        session[_STATE_KEY] = state

    if request.method == "POST":
        submitted = request.form.get("attempt_token", "")
        if not submitted or not secrets.compare_digest(str(state["token"]), submitted):
            abort(400, description="Недійсний токен спроби")
        action = request.form.get("action", "")

        if action == "restart":
            session[_STATE_KEY] = _new_attempt(game["id"], questions)
            return redirect(url_for("interactive.play_game", token=token), code=303)

        if action == "answer":
            if state["phase"] != "question":
                abort(409, description="Відповідь уже зарахована")
            step = len(state["answers"])
            if step >= len(questions):
                abort(409, description="Усі запитання вже завершені")
            answer = request.form.get("answer", "").strip().upper()
            allowed = {"A", "B"} if mode == "true_false" else _LETTERS
            if answer not in allowed:
                flash("Обери Правду або Неправду." if mode == "true_false"
                      else "Обери один із чотирьох варіантів відповіді.")
                return redirect(url_for("interactive.play_game", token=token), code=303)
            try:
                submitted_id = int(request.form.get("question_id", ""))
            except (TypeError, ValueError):
                abort(400, description="Некоректне запитання")
            if submitted_id != int(questions[step]["id"]):
                abort(409, description="Порядок запитань порушено")
            state["answers"].append(answer)
            state["phase"] = "feedback"
            session[_STATE_KEY] = state
            return redirect(url_for("interactive.play_game", token=token), code=303)

        if action == "next":
            if state["phase"] != "feedback":
                abort(409, description="Спочатку дай відповідь")
            if len(state["answers"]) < len(questions):
                state["phase"] = "question"
            else:
                # Save only once during the normal completion flow.
                if not state["saved"] and session.get("user_id") is not None:
                    result = _result(questions, state["answers"])
                    save_game_result(
                        user_id=session["user_id"], game_id=game["id"],
                        score=result["score"], total_questions=result["total"],
                        correct_answers=result["score"],
                    )
                    state["saved"] = True
                state["phase"] = "complete"
            session[_STATE_KEY] = state
            return redirect(url_for("interactive.play_game", token=token), code=303)
        abort(400, description="Невідома дія")

    # GET: no mutation of the active attempt, so refreshing never erases progress.
    answers = state["answers"]
    phase = state["phase"]
    context = {
        "game": game, "phase": phase, "total": len(questions),
        "is_true_false": mode == "true_false",
        "answered": len(answers), "attempt_token": state["token"],
    }
    from gamification_store import streak_stats, display_xp
    answer_sequence = [str(answer).strip().upper() == str(q["correct_answer"]).strip().upper()
                       for answer, q in zip(answers, questions)]
    current_streak, best_streak = streak_stats(answer_sequence)
    context.update(current_streak=current_streak, best_streak=best_streak)
    if phase == "question":
        context["question"] = questions[len(answers)]
    elif phase == "feedback":
        q = questions[len(answers) - 1]
        actual = q["correct_answer"].strip().upper()
        context.update(
            question=q,
            selected=answers[-1],
            selected_text=_option_text(q, answers[-1]),
            correct=actual,
            correct_text=_option_text(q, actual),
            explanation=_clean_explanation(q["explanation"]),
            is_correct=answers[-1] == actual,
        )
    else:
        context["result"] = _result(questions, answers)
        context["result_saved"] = bool(state["saved"])
    return render_template("interactive_game.html", **context)
