"""Subscription workflows. All state-changing browser endpoints use login+CSRF.
Gateway callbacks are cryptographically validated and NEVER use browser session.
"""
from __future__ import annotations

import hashlib
import os
import secrets

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

import premium_v2_gateway as gateway
import premium_v2_store as store

premium_v2_bp=Blueprint('premium_v2',__name__)


def enabled():
    return gateway.only_test_environment()


def require_test_mode():
    if not enabled():
        abort(404)


def current_user():
    user_id=session.get('user_id')
    if not isinstance(user_id,int) or user_id<1:
        return None
    return user_id


def require_user():
    user_id=current_user()
    if user_id is None:
        flash('Спочатку увійдіть до системи.')
        return None
    return user_id


def csrf_token():
    token=session.get('premium_v2_csrf')
    if not token:
        token=secrets.token_urlsafe(32)
        session['premium_v2_csrf']=token
    return token


def check_csrf():
    given=request.form.get('premium_v2_csrf','')
    expected=session.get('premium_v2_csrf','')
    if not given or not expected or not secrets.compare_digest(given,expected):
        abort(400,description='Недійсний захисний токен')


def provider():
    value=os.getenv('SUBSCRIPTIONS_TEST_PROVIDER','local').strip().lower()
    if value not in ('local','liqpay'):
        raise RuntimeError('Невідомий SUBSCRIPTIONS_TEST_PROVIDER')
    return value


def local_developer_only(user_id):
    expected=os.getenv('DEV_USER_ID','').strip()
    if not (provider()=='local' and request.remote_addr in ('127.0.0.1','::1')
            and expected.isdecimal() and int(expected)==user_id):
        abort(403,description='Симулятор доступний тільки розробнику з локального комп’ютера')


def liqpay_developer_only(user_id):
    """Only the local developer can start sandbox LiqPay checkouts."""
    expected=os.getenv('DEV_USER_ID','').strip()
    if not (provider()=='liqpay' and request.remote_addr in ('127.0.0.1','::1')
            and expected.isdecimal() and int(expected)==user_id):
        abort(403, description='LiqPay Sandbox доступний тільки локальному акаунту розробника')


@premium_v2_bp.before_app_request
def keep_plans_current():
    # No change on production; requests expire only overdue sandbox subscriptions.
    if enabled():
        store.expire_due()


@premium_v2_bp.get('/premium-v2')
def subscription_page():
    require_test_mode()
    user_id=require_user()
    if user_id is None:
        return redirect(url_for('login'))
    from database import get_user_game_quota
    quota=get_user_game_quota(user_id)
    if quota is None:
        session.clear()
        return redirect(url_for('login'))
    order=store.latest_for_user(user_id)
    test_local=provider()=='local'
    return render_template('premium_v2.html',quota=quota,order=order,
            local=test_local,dev=bool(os.getenv('DEV_USER_ID','').isdigit()
              and int(os.getenv('DEV_USER_ID'))==user_id
              and request.remote_addr in ('127.0.0.1','::1')),
            csrf=csrf_token(),price_minor=store.PRICE_MINOR)


@premium_v2_bp.post('/premium-v2/start')
def start():
    require_test_mode()
    user_id=require_user()
    if user_id is None:
        return redirect(url_for('login'))
    check_csrf()
    choice=provider()
    if choice=='local':
        local_developer_only(user_id)
    else:
        liqpay_developer_only(user_id)
        gateway.merchant_keys()
        gateway.callback_base_url()
    try:
        order=store.create_order(user_id,choice)
    except ValueError as error:
        flash(str(error))
        return redirect(url_for('premium_v2.subscription_page'))
    if choice=='liqpay':
        return redirect(url_for('premium_v2.checkout',order_id=order['order_id']))
    flash('Створено тестове замовлення. Симулюй успішну оплату або відмову.')
    return redirect(url_for('premium_v2.subscription_page'))


@premium_v2_bp.get('/premium-v2/checkout/<order_id>')
def checkout(order_id):
    require_test_mode()
    user_id=require_user()
    if user_id is None:
        return redirect(url_for('login'))
    liqpay_developer_only(user_id)
    order=store.by_order(order_id)
    if order is None or order['user_id']!=user_id or order['provider']!='liqpay':
        abort(404)
    if order['status']!='pending':
        return redirect(url_for('premium_v2.subscription_page'))
    fields=gateway.checkout_fields(order)
    return render_template('premium_v2_checkout.html',fields=fields,order=order)


@premium_v2_bp.get('/premium-v2/return')
def payment_return():
    require_test_mode()
    flash('Повернення зі сторінки оплати не активує Premium. Очікуємо перевірений callback від LiqPay.')
    return redirect(url_for('premium_v2.subscription_page'))


@premium_v2_bp.post('/premium-v2/liqpay/callback')
def liqpay_callback():
    require_test_mode()
    if provider()!='liqpay':
        abort(404)
    try:
        payload=gateway.decode_verified_callback(request.form.get('data',''),
                                                  request.form.get('signature',''))
        order_id=str(payload.get('order_id',''))
        order=store.by_order(order_id)
        if not order or order['provider']!='liqpay':
            abort(404)
        # Never trust paid amount/currency/order just because the signature validates.
        if str(payload.get('currency',''))!=order['currency']:
            abort(400)
        try:
            amount_minor=round(float(payload.get('amount',''))*100)
        except (ValueError,TypeError,OverflowError):
            abort(400)
        if amount_minor!=order['amount_minor']:
            abort(400)
        raw_status=str(payload.get('status','')).lower()
        action=str(payload.get('action','')).lower()
        if action not in ('subscribe','regular','pay'):
            return 'ignored',200
        if raw_status in ('sandbox','subscribed','success'):
            status='approved'
        elif raw_status in ('failure','error'):
            status='declined'
        else:
            return 'waiting',200
        event_ref=str(payload.get('transaction_id') or payload.get('payment_id') or '').strip()
        if action=='regular' and not event_ref:
            return 'unidentified renewal',200
        event_key='liqpay:'+hashlib.sha256(
            (order_id+'|'+action+'|'+raw_status+'|'+(event_ref or request.form['data'])).encode('utf-8')
        ).hexdigest()
        store.apply_event(order_id,event_key,status,'renewal' if action=='regular' else 'initial',event_ref)
        return 'ok',200
    except ValueError:
        abort(400)


@premium_v2_bp.post('/premium-v2/cancel')
def cancel():
    require_test_mode()
    user_id=require_user()
    if user_id is None:
        return redirect(url_for('login'))
    check_csrf()
    order=store.latest_for_user(user_id)
    if not order or order['status'] not in ('pending','active','cancel_pending'):
        flash('Немає активної підписки для скасування.')
        return redirect(url_for('premium_v2.subscription_page'))
    if order['status']=='cancel_pending':
        flash('Автопродовження вже вимкнено.')
    elif order['provider']=='liqpay' and order['status']=='active':
        try:
            if not gateway.cancel_renewals(order['order_id']):
                flash('LiqPay не підтвердив скасування. Повтори дію; підписка поки не змінена.')
                return redirect(url_for('premium_v2.subscription_page'))
        except Exception:
            flash('Немає підтвердження від LiqPay. Статус залишився без змін.')
            return redirect(url_for('premium_v2.subscription_page'))
        store.mark_cancelled(order['order_id'],user_id)
        flash('Автопродовження вимкнено. Premium діє до кінця оплаченого періоду.')
    else:
        store.mark_cancelled(order['order_id'],user_id)
        flash('Підписку скасовано; поточний оплачений період збережено, якщо він є.')
    return redirect(url_for('premium_v2.subscription_page'))


@premium_v2_bp.post('/premium-v2/simulate')
def simulate():
    require_test_mode()
    user_id=require_user()
    if user_id is None:
        return redirect(url_for('login'))
    check_csrf()
    local_developer_only(user_id)
    event=request.form.get('event','')
    order=store.latest_for_user(user_id)
    if order is None or order['provider']!='local':
        abort(400)
    if event=='success' and order['status']=='pending':
        result=store.apply_event(order['order_id'],'local:'+secrets.token_hex(18),
                                 'approved','initial')
    elif event=='decline' and order['status']=='pending':
        result=store.apply_event(order['order_id'],'local:'+secrets.token_hex(18),
                                 'declined','initial')
    elif event=='renew' and order['status']=='active':
        result=store.apply_event(order['order_id'],'local:'+secrets.token_hex(18),
                                 'approved','renewal')
    elif event=='expire' and order['status'] in ('active','cancel_pending'):
        store.force_expire_test(order['order_id'],user_id)
        store.expire_due()
        result='expired'
    else:
        abort(400,description='Ця тестова операція недоступна для поточного статусу')
    flash('Результат тестової операції: '+result)
    return redirect(url_for('premium_v2.subscription_page'))
