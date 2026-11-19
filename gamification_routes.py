"""Authenticated, read-only gamification dashboard."""
from flask import Blueprint, redirect, render_template, session, url_for
from database import get_user_by_id, get_user_game_quota
from gamification_store import progress_for_user


gamification_bp = Blueprint('gamification', __name__)


@gamification_bp.get('/my-progress')
def my_progress():
    user_id = session.get('user_id')

    if user_id is None:
        return redirect(url_for('login'))

    user = get_user_by_id(user_id)

    if user is None:
        session.clear()
        return redirect(url_for('login'))

    # Отримання прогресу користувача
    progress = progress_for_user(user_id)

    # Визначення тарифного плану
    quota = get_user_game_quota(user_id)
    plan = str(quota['plan']).strip().lower()

    # Для Free показуємо тільки 5 останніх проходжень
    if plan == 'free':
        progress['recent'] = progress['recent'][:5]

    return render_template(
        'gamification_progress.html',
        user=user,
        progress=progress
    )
