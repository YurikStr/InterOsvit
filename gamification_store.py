"""Achievements and XP for InterOsvit (SQLite; no OpenAI calls).

Existing result persistence remains in database.save_game_result(). This module
reserves a signed-session attempt key before the old save and finalizes the XP
award afterwards. It prevents repeated submission of the SAME attempt from
creating another result or award. It does not stop a user playing again with a
new attempt token. Old result history is imported once with streak=0.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import sqlite3

from dotenv import load_dotenv

load_dotenv()

MODES = {'classic', 'interactive', 'true_false', 'matching'}
LEVEL_XP = 200


def db_path() -> Path:
    configured = os.getenv('INTEROSVIT_DB_PATH', '').strip()
    path = Path(configured) if configured else Path(__file__).resolve().with_name('interosvit.db')
    if not path.is_file():
        raise RuntimeError(f'Базу даних InterOsvit не знайдено: {path}')
    return path


def connect_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path()), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=20000')
    return db


def xp_for(score: int, total: int, best_streak: int = 0) -> int:
    if not (type(score) is int and type(total) is int and type(best_streak) is int and
            0 <= score <= total <= 20 and 0 <= best_streak <= total):
        raise ValueError('Некоректний результат проходження')
    if total == 0:
        return 0
    return 10 + 10 * score + (20 if score == total else 0) + 2 * best_streak


# INTEROSVIT_REPEAT_XP_25_V1
# Only new attempts are discounted. Existing awarded XP never changes.
def repeat_xp(full_xp: int) -> int:
    """25 percent of base XP, rounded half-up to a whole point."""
    if type(full_xp) is not int or full_xp < 0:
        raise ValueError('Некоректна сума XP')
    return (full_xp + 2) // 4


def streak_stats(correctness) -> tuple[int, int]:
    current = best = 0
    for valid in correctness:
        if type(valid) is not bool:
            raise ValueError('Послідовність має містити лише True/False')
        current = current + 1 if valid else 0
        best = max(best, current)
    return current, best


def _required_tables(db):
    required = {
        'results': {'id', 'user_id', 'game_id', 'score', 'total_questions', 'correct_answers'},
        'users': {'id'},
        'games': {'id'},
    }
    for table, cols in required.items():
        existing = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
        if not cols.issubset(existing):
            raise RuntimeError(f'У {table} відсутні поля: {sorted(cols - existing)}')


def migrate() -> dict:
    """Idempotent migration; imports results existing before first install."""
    db = connect_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        _required_tables(db)
        db.execute('''CREATE TABLE IF NOT EXISTS gamification_attempts (
            attempt_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            correct INTEGER NOT NULL,
            best_streak INTEGER NOT NULL DEFAULT 0,
            xp INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
            legacy INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE INDEX IF NOT EXISTS idx_gamification_user
                      ON gamification_attempts(user_id, status, completed_at)''')
        db.execute('''CREATE TABLE IF NOT EXISTS gamification_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )''')
        has_marker = db.execute(
            "SELECT 1 FROM gamification_meta WHERE key='legacy_backfilled'"
        ).fetchone()
        imported = 0
        if not has_marker:
            results_cols = {r['name'] for r in db.execute('PRAGMA table_info(results)')}
            games_cols = {r['name'] for r in db.execute('PRAGMA table_info(games)')}
            completed_sql = 'r.completed_at' if 'completed_at' in results_cols else 'CURRENT_TIMESTAMP'
            mode_sql = "COALESCE(g.game_mode, 'classic')" if 'game_mode' in games_cols else "'classic'"
            rows = db.execute(f'''SELECT r.id, r.user_id, r.game_id, r.score,
                                      r.total_questions, r.correct_answers,
                                      {completed_sql} AS completed_at,
                                      {mode_sql} AS game_mode
                               FROM results AS r LEFT JOIN games AS g ON g.id=r.game_id
                               ORDER BY r.id''').fetchall()
            for row in rows:
                correct = int(row['correct_answers'] or 0)
                total = int(row['total_questions'] or 0)
                score = int(row['score'] or 0)
                # Historical results are trusted only as far as their existing values.
                if not (0 <= score <= total <= 20 and 0 <= correct <= total):
                    continue
                mode = row['game_mode'] if row['game_mode'] in MODES else 'classic'
                db.execute('''INSERT OR IGNORE INTO gamification_attempts
                    (attempt_hash,user_id,game_id,mode,score,total,correct,
                     best_streak,xp,status,legacy,completed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,'completed',1,?)''',
                    (f'legacy:{row["id"]}', row['user_id'], row['game_id'], mode,
                     score, total, correct, 0, xp_for(correct, total),
                     row['completed_at'] or '1970-01-01 00:00:00'))
                imported += 1
            db.execute("INSERT INTO gamification_meta(key,value) VALUES('legacy_backfilled','1')")
        db.commit()
        return {'imported': imported, 'already_migrated': bool(has_marker)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _request_metadata(game_id: int, score: int, total: int) -> tuple[str, str, int]:
    """Read server-validated results from the current Flask request context.

    Never read correctness or XP from the client-supplied POST directly without
    comparing against server-side question keys and trusted session state.
    """
    known_route = False
    try:
        from flask import has_request_context, request, session
        if not has_request_context():
            raise LookupError('Outside HTTP request')
        from database import get_game_questions
        questions = get_game_questions(game_id)
        if len(questions) != total:
            raise LookupError('Question set changed during attempt')
        endpoint = request.endpoint or ''
        known_route = endpoint in ('game_page', 'interactive.play_game', 'matching.play_game')
        if endpoint == 'game_page':
            attempt = session.get(f'attempt_{game_id}')
            sequence = [request.form.get(f'question_{q["id"]}', '').strip().upper()
                        == str(q['correct_answer']).strip().upper() for q in questions]
            if not isinstance(attempt, str) or len(attempt) < 16:
                raise LookupError('Missing classic attempt')
            mode = 'classic'
        elif endpoint == 'interactive.play_game':
            state = session.get('io_interactive_attempt_v1', {})
            attempt = state.get('token', '')
            answers = state.get('answers', [])
            if state.get('game_id') != game_id or len(answers) != total:
                raise LookupError('Interactive attempt mismatch')
            sequence = [str(a).strip().upper() == str(q['correct_answer']).strip().upper()
                        for a, q in zip(answers, questions)]
            # Authenticated game mode comes from SQLite; not the request form.
            mode = 'interactive'
        elif endpoint == 'matching.play_game':
            state = session.get('io_matching_attempt_v1', {})
            attempt = state.get('token', '')
            if state.get('game_id') != game_id or not state.get('complete', False) and len(state.get('matched', [])) != total:
                raise LookupError('Matching attempt mismatch')
            events = state.get('events')
            if isinstance(events, list) and len(events) <= 100 and all(type(v) is bool for v in events):
                sequence = events
            else:
                mistaken = set(state.get('mistaken', []))
                sequence = [qid not in mistaken for qid in state.get('matched', [])]
            mode = 'matching'
        else:
            raise LookupError('Unknown game endpoint')
        if not isinstance(attempt, str) or len(attempt) < 16:
            raise LookupError('Missing attempt token')
        if mode != 'matching' and sum(sequence) != score:
            raise LookupError('Score mismatch')
        if mode == 'matching' and sum(x not in set(state['mistaken']) for x in state['matched']) != score:
            raise LookupError('Matching score mismatch')
        db = connect_db()
        try:
            g = db.execute('SELECT game_mode FROM games WHERE id=?', (game_id,)).fetchone()
            if g and g['game_mode'] in MODES:
                mode = g['game_mode']
        finally:
            db.close()
        return mode, attempt, streak_stats(sequence)[1]
    except (LookupError, KeyError, TypeError, ValueError, IndexError, sqlite3.Error, ImportError) as exc:
        if known_route:
            # A recognized game must never bypass attempt replay protection.
            raise RuntimeError('Не вдалося підтвердити унікальність спроби гри') from exc
        # Compatibility fallback for nonstandard custom routes and CLI callers.
        return 'classic', secrets.token_urlsafe(24), 0


def save_with_gamification(original_save, *args, **kwargs):
    """Wrap the existing database.save_game_result without changing its SQL.

    In a race, only the first submission of a given attempt is allowed to call
    the original persistence function. pending rows are intentionally visible
    only internally and do not grant XP. A process crash between the two DB
    commits can leave a pending marker, requiring manual reconciliation.
    """
    names = ('user_id', 'game_id', 'score', 'total_questions', 'correct_answers')
    values = dict(zip(names, args))
    values.update(kwargs)
    if any(k not in values for k in names):
        raise ValueError('Невідомий формат збереження результату гри')
    user_id = int(values['user_id'])
    game_id = int(values['game_id'])
    score = int(values['score'])
    total = int(values['total_questions'])
    correct = int(values['correct_answers'])
    if not (0 <= score <= total <= 20 and correct == score):
        raise ValueError('Некоректні бали гри')
    mode, token, best_streak = _request_metadata(game_id, score, total)
    best_streak = min(best_streak, total)
    nonce = hashlib.sha256(f'{user_id}:{game_id}:{mode}:{token}'.encode()).hexdigest()
    db = connect_db()
    try:
        # Unique key serializes concurrent repeated submissions of one attempt.
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT status FROM gamification_attempts WHERE attempt_hash=?', (nonce,)).fetchone()
        if existing:
            db.rollback()
            return None  # Already saved or in progress; never double-insert result.
        db.execute('''INSERT INTO gamification_attempts
                 (attempt_hash,user_id,game_id,mode,score,total,correct,best_streak,xp,status)
                 VALUES(?,?,?,?,?,?,?,?,0,'pending')''',
                 (nonce,user_id,game_id,mode,score,total,correct,best_streak))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    try:
        answer = original_save(*args, **kwargs)
    except Exception:
        cleanup = connect_db()
        try:
            cleanup.execute("DELETE FROM gamification_attempts WHERE attempt_hash=? AND status='pending'", (nonce,))
            cleanup.commit()
        finally:
            cleanup.close()
        raise
    db = connect_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        # Under BEGIN IMMEDIATE, this check and award are serialized.
        # The current attempt is still pending, so only PREVIOUS completed
        # attempts count. This includes legacy attempts imported at migration.
        previous = db.execute(
            """SELECT 1 FROM gamification_attempts
               WHERE user_id=? AND game_id=? AND status='completed' LIMIT 1""",
            (user_id, game_id),
        ).fetchone()
        base_xp = xp_for(correct, total, best_streak)
        awarded_xp = repeat_xp(base_xp) if previous else base_xp
        db.execute('''UPDATE gamification_attempts SET status='completed',xp=?
                      WHERE attempt_hash=? AND status='pending' ''',
                   (awarded_xp, nonce))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return answer


def _completed_attempt_xp_in_request() -> int | None:
    """Read the exact saved award for the active signed-session attempt.

    Prevents the result page from saying +full XP for a repeat play that
    actually earned 25%. Never trusts XP supplied by a browser/form.
    """
    try:
        from flask import has_request_context, request, session
        if not has_request_context():
            return None
        if request.endpoint == 'interactive.play_game':
            state = session.get('io_interactive_attempt_v1')
            modes = ('interactive', 'true_false')
        elif request.endpoint == 'matching.play_game':
            state = session.get('io_matching_attempt_v1')
            modes = ('matching',)
        else:
            return None
        if not isinstance(state, dict) or state.get('saved') is not True:
            return None
        user_id, game_id, token = session.get('user_id'), state.get('game_id'), state.get('token')
        if type(user_id) is not int or type(game_id) is not int:
            return None
        if not isinstance(token, str) or len(token) < 16:
            return None
        hashes = [hashlib.sha256(f'{user_id}:{game_id}:{mode}:{token}'.encode()).hexdigest()
                  for mode in modes]
        db = connect_db()
        try:
            placeholders = ','.join('?' for _ in hashes)
            row = db.execute(
                f"""SELECT xp FROM gamification_attempts
                     WHERE user_id=? AND game_id=? AND status='completed'
                       AND attempt_hash IN ({placeholders}) LIMIT 1""",
                (user_id, game_id, *hashes),
            ).fetchone()
        finally:
            db.close()
        return int(row['xp']) if row else None
    except (ImportError, OSError, sqlite3.Error, TypeError, ValueError):
        return None


def display_xp(score: int, total: int, correctness) -> int:
    """Actual persisted award on game result pages; base XP otherwise."""
    actual = _completed_attempt_xp_in_request()
    if actual is not None:
        return actual
    seq = list(correctness)
    return xp_for(int(score), int(total), streak_stats(seq)[1])


ACHIEVEMENTS = (
    ('first', 'Перший крок', 'Пройди одну навчальну гру.'),
    ('five', 'Наполегливий учень', 'Пройди 5 ігор.'),
    ('ten', 'Досвідчений гравець', 'Пройди 10 ігор.'),
    ('perfect', 'Без помилок', 'Заверши гру з максимальним результатом.'),
    ('streak3', 'Серія ×3', 'Дай 3 правильні відповіді поспіль.'),
    ('streak5', 'Серія ×5', 'Дай 5 правильних відповідей поспіль.'),
    ('explorer', 'Дослідник', 'Пройди 3 різні ігри.'),
    ('modes', 'Універсал', 'Пройди ігри в усіх 4 режимах.'),
    ('xp500', '500 XP', 'Назбирай 500 очок досвіду.'),
)


def progress_for_user(user_id: int | None) -> dict:
    if user_id is None:
        return {}
    db = connect_db()
    try:
        row = db.execute('''SELECT COUNT(*) AS played, COALESCE(SUM(xp),0) AS xp,
                                 COALESCE(SUM(correct),0) AS correct,
                                 COALESCE(SUM(total),0) AS total,
                                 COALESCE(MAX(best_streak),0) AS best_streak,
                                 COUNT(DISTINCT game_id) AS distinct_games,
                                 COUNT(DISTINCT CASE WHEN mode IN ('classic','interactive','true_false','matching')
                                                     THEN mode END) AS modes,
                                 COALESCE(SUM(CASE WHEN total>0 AND score=total THEN 1 ELSE 0 END),0) AS perfect
                          FROM gamification_attempts
                          WHERE user_id=? AND status='completed' ''', (user_id,)).fetchone()
        data = dict(row)
        recent = [dict(x) for x in db.execute('''SELECT game_id,mode,score,total,best_streak,xp,legacy,completed_at
                       FROM gamification_attempts WHERE user_id=? AND status='completed'
                       ORDER BY completed_at DESC, rowid DESC LIMIT 10''', (user_id,))]
    finally:
        db.close()
    xp = int(data['xp'])
    data.update(level=xp // LEVEL_XP + 1, within_level=xp % LEVEL_XP,
                next_level_xp=LEVEL_XP, remaining_xp=LEVEL_XP - xp % LEVEL_XP,
                accuracy=round(100 * data['correct'] / data['total']) if data['total'] else 0,
                recent=recent)
    unlocked = {
        'first': data['played'] >= 1,
        'five': data['played'] >= 5,
        'ten': data['played'] >= 10,
        'perfect': data['perfect'] >= 1,
        'streak3': data['best_streak'] >= 3,
        'streak5': data['best_streak'] >= 5,
        'explorer': data['distinct_games'] >= 3,
        'modes': data['modes'] >= 4,
        'xp500': xp >= 500,
    }
    data['achievements'] = [dict(id=k,title=title,description=desc,unlocked=unlocked[k])
                            for k,title,desc in ACHIEVEMENTS]
    data['unlocked_count'] = sum(unlocked.values())
    return data
