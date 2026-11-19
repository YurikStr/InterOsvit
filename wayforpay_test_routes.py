"""Separate WayForPay integration smoke test, not a production payment endpoint."""
from __future__ import annotations

import json
import os
import secrets
import time

from dotenv import load_dotenv
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, jsonify

import wayforpay_test_gateway as gateway
import wayforpay_test_store as store

load_dotenv()
wayforpay_test_bp=Blueprint('wayforpay_test', __name__)


def require_developer():
    try:
        gateway.sandbox_guard()
    except RuntimeError:
        abort(404)
    user=session.get('user_id')
    dev=os.getenv('DEV_USER_ID','').strip()
    if request.remote_addr not in ('127.0.0.1','::1') or not dev.isdecimal() or user != int(dev):
        abort(403)
    return user


def csrf_token():
    token=session.get('wayforpay_test_csrf')
    if not token:
        token=secrets.token_urlsafe(24)
        session['wayforpay_test_csrf']=token
    return token


def check_csrf():
    supplied=request.form.get('wayforpay_test_csrf','')
    expected=session.get('wayforpay_test_csrf','')
    if not supplied or not expected or not secrets.compare_digest(supplied,expected):
        abort(400)


@wayforpay_test_bp.get('/wayforpay-test')
def index():
    uid=require_developer()
    try:
        base=gateway.public_base()
    except RuntimeError as ex:
        base=None
        message=str(ex)
    else:
        message=None
    return render_template('wayforpay_test.html', order=store.latest(uid),csrf=csrf_token(),
                           base=base,error=message)


@wayforpay_test_bp.post('/wayforpay-test/new')
def new():
    uid=require_developer()
    check_csrf()
    gateway.public_base()
    order=store.new_order(uid)
    return redirect(url_for('wayforpay_test.checkout',order_ref=order['order_ref']))


@wayforpay_test_bp.get('/wayforpay-test/checkout/<order_ref>')
def checkout(order_ref):
    uid=require_developer()
    order=store.get(order_ref)
    if not order or order['user_id']!=uid:
        abort(404)
    if order['status']!='pending':
        return redirect(url_for('wayforpay_test.index'))
    fields=gateway.purchase_fields(order)
    return render_template('wayforpay_test_checkout.html',order=order,fields=fields,action=gateway.PAY_URL)


@wayforpay_test_bp.route('/wayforpay-test/return',methods=['GET','POST'])
def returned():
    # Browser redirects do NOT approve a transaction or modify any account data.
    return redirect(url_for('wayforpay_test.index'))


@wayforpay_test_bp.post('/wayforpay-test/callback')
def callback():
    try:
        gateway.sandbox_guard()
    except RuntimeError:
        abort(404)
    if request.content_length is not None and request.content_length>32768:
        abort(413)
    if not request.is_json:
        abort(415)
    payload=request.get_json(silent=True)
    try:
        gateway.verify_callback(payload)
        order=store.get(payload['orderReference'])
        if order is None:
            abort(404)
        if payload['currency'] != order['currency'] or gateway.minor_from_amount(payload['amount']) != order['amount_minor']:
            abort(400)
        # Only accept approved with documented reasonCode 1100.
        if payload['transactionStatus']=='Approved' and str(payload['reasonCode']) != '1100':
            abort(400)
        store.apply_verified_callback(payload)
    except ValueError:
        abort(400)
    return jsonify(gateway.acknowledgment(order['order_ref'],int(time.time())))
