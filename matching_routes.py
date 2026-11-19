"""Public matching game, server-validated submissions, author game token.

MVP attempt state is stored in a Flask signed cookie (not encrypted). Opaque
item handles are HMACed with the app secret, so their visible values do not
reveal which two items correspond. For production use server-side attempts with
unique completion constraints for stronger idempotence across parallel tabs.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, session, url_for)

from database import get_game_by_token, get_game_questions, save_game_result
from game_settings import get_game_settings
from matching_mode import validate_saved_rows

matching_bp = Blueprint("matching", __name__)
_STATE_KEY = "io_matching_attempt_v1"
MAX_WRONG_PER_ATTEMPT = 60


def _signature(questions) -> str:
    """Detect edits during a play-through and reset instead of mixing versions."""
    h = hashlib.sha256()
    for q in questions:
        for key in ("id", "question_text", "option_a", "explanation"):
            h.update(str(q[key]).encode("utf-8"))
            h.update(b"\x00")
    return h.hexdigest()[:24]


def _new_attempt(game_id: int, questions) -> dict:
    ids = [int(q["id"]) for q in questions]
    return {"game_id": int(game_id), "signature": _signature(questions),
            "token": secrets.token_urlsafe(32),
            "right_order": secrets.SystemRandom().sample(ids, len(ids)),
            "matched": [], "mistaken": [], "wrong_count": 0,
            "last_success": None, "complete": False, "saved": False, "events": []}


def _opaque(item_id: int, role: str, token: str) -> str:
    secret = current_app.secret_key
    if not isinstance(secret, bytes):
        secret = str(secret).encode("utf-8")
    raw = f"{token}:{role}:{item_id}".encode("utf-8")
    return hmac.new(secret, raw, hashlib.sha256).hexdigest()[:32]


def _answer_score(state: dict) -> int:
    return len(set(state["matched"]) - set(state["mistaken"]))


def _state_valid(state: object, game_id: int, questions) -> bool:
    if not isinstance(state, dict):
        return False
    ids = [int(q["id"]) for q in questions]
    matched = state.get("matched")
    mistaken = state.get("mistaken")
    right_order = state.get("right_order")
    return (
        state.get("game_id") == game_id
        and state.get("signature") == _signature(questions)
        and isinstance(state.get("token"), str) and len(state["token"]) >= 32
        and isinstance(right_order, list) and sorted(right_order) == sorted(ids)
        and isinstance(matched, list) and len(matched) == len(set(matched))
        and all(item in ids for item in matched)
        and isinstance(mistaken, list) and len(mistaken) == len(set(mistaken))
        and all(item in ids for item in mistaken)
        and type(state.get("wrong_count")) is int and 0 <= state["wrong_count"] <= MAX_WRONG_PER_ATTEMPT
        and isinstance(state.get("events"), list) and len(state["events"]) <= 80
        and all(type(flag) is bool for flag in state["events"])
        and type(state.get("complete")) is bool and type(state.get("saved")) is bool
    )


@matching_bp.route("/match/<token>", methods=["GET", "POST"])
def play_game(token):
    game = get_game_by_token(token)
    if game is None:
        abort(404)
    if get_game_settings(game["id"])["game_mode"] != "matching":
        return redirect(url_for("game_page", token=token))

    questions = get_game_questions(game["id"])
    if not questions:
        return render_template("matching_game.html", game=game, phase="empty")
    if len(questions) > 20 or validate_saved_rows(questions):
        return render_template("matching_game.html", game=game, phase="unavailable"), 503

    by_id = {int(q["id"]): q for q in questions}
    state = session.get(_STATE_KEY)
    if not _state_valid(state, int(game["id"]), questions):
        state = _new_attempt(int(game["id"]), questions)
        session[_STATE_KEY] = state

    if request.method == "POST":
        supplied_token = request.form.get("attempt_token", "")
        if not isinstance(supplied_token, str) or not secrets.compare_digest(state["token"], supplied_token):
            abort(403, "Недійсний токен проходження")
        action = request.form.get("action", "")
        if action == "restart":
            session[_STATE_KEY] = _new_attempt(int(game["id"]), questions)
            return redirect(url_for("matching.play_game", token=token), code=303)
        if action != "check":
            abort(400, "Невідома дія")
        if state["complete"] or state["wrong_count"] >= MAX_WRONG_PER_ATTEMPT:
            abort(409, "Спробу завершено. Почни нову гру")
        remaining = [qid for qid in by_id if qid not in state["matched"]]
        left_map = {_opaque(i, "L", state["token"]): i for i in remaining}
        right_map = {_opaque(i, "R", state["token"]): i for i in remaining}
        left = left_map.get(request.form.get("left_key", ""))
        right = right_map.get(request.form.get("right_key", ""))
        if left is None or right is None:
            abort(400, "Обери два доступні елементи")
        state["events"].append(left == right)
        if left == right:
            state["matched"].append(left)
            state["last_success"] = left
            if len(state["matched"]) == len(questions):
                if not state["saved"] and session.get("user_id") is not None:
                    score = _answer_score(state)
                    save_game_result(user_id=session["user_id"],
                                     game_id=game["id"], score=score,
                                     total_questions=len(questions),
                                     correct_answers=score)
                    state["saved"] = True
                state["complete"] = True
            flash("Правильна пара знайдена!")
        else:
            if left not in state["mistaken"]:
                state["mistaken"].append(left)
            state["wrong_count"] += 1
            state["last_success"] = None
            flash("Це не відповідна пара. Спробуй ще раз.")
        session[_STATE_KEY] = state
        return redirect(url_for("matching.play_game", token=token), code=303)

    total = len(questions)
    matched = set(state["matched"])
    left_items = [
        {"key": _opaque(int(q["id"]), "L", state["token"]),
         "text": q["question_text"]}
        for q in questions if int(q["id"]) not in matched
    ]
    right_items = [
        {"key": _opaque(qid, "R", state["token"]),
         "text": by_id[qid]["option_a"]}
        for qid in state["right_order"] if qid not in matched
    ]
    review = [{"left": q["question_text"], "right": q["option_a"],
               "explanation": q["explanation"],
               "first_try": int(q["id"]) not in state["mistaken"]}
              for q in questions] if state["complete"] else []
    last = by_id.get(state.get("last_success")) if state.get("last_success") else None
    from gamification_store import streak_stats, display_xp
    current_streak, _ = streak_stats(state["events"])
    return render_template(
        "matching_game.html", game=game,
        phase=("complete" if state["complete"] else
               "limited" if state["wrong_count"] >= MAX_WRONG_PER_ATTEMPT else "playing"),
        attempt_token=state["token"], total=total, matched=len(matched),
        score=_answer_score(state), wrong_count=state["wrong_count"],
        current_streak=current_streak,
        xp_earned=display_xp(_answer_score(state), total, state["events"]),
        left_items=left_items, right_items=right_items,
        last=last, review=review, result_saved=state["saved"],
    )
