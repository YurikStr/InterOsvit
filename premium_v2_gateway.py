"""LiqPay TEST KEYS ONLY. No payment card handling and no production payments.

LiqPay checkout/signature parameters based on LiqPay API v7 docs (Nov 2026).
Never enable this module as live checkout without a separate production review.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_VERSION = 7
CHECKOUT_URL = 'https://www.liqpay.ua/api/3/checkout'
REQUEST_URL = 'https://www.liqpay.ua/api/request'


def only_test_environment() -> bool:
    return (os.getenv('APP_ENV', 'development').strip().lower() == 'development'
            and os.getenv('SUBSCRIPTIONS_TEST_MODE','false').strip().lower() == 'true'
            and os.getenv('ENABLE_DEMO_PREMIUM','false').strip().lower() != 'true')


def merchant_keys() -> tuple[str,str]:
    if not only_test_environment():
        raise RuntimeError('Premium v2 доступний лише у тестовому середовищі')
    pub=os.getenv('LIQPAY_PUBLIC_KEY','').strip()
    private=os.getenv('LIQPAY_PRIVATE_KEY','').strip()
    if not pub.startswith('sandbox_') or not private.startswith('sandbox_'):
        raise RuntimeError('Для LiqPay дозволені лише тестові ключі з префіксом sandbox_')
    return pub,private


def callback_base_url() -> str:
    base = os.getenv('PREMIUM_V2_PUBLIC_BASE_URL','').strip().rstrip('/')
    if not base.startswith('https://') or any(x in base.lower() for x in ('localhost','127.0.0.1','0.0.0.0')):
        raise RuntimeError('Для LiqPay потрібен зовнішній HTTPS URL для server-to-server callback')
    if '?' in base or '#' in base or '@' in base:
        raise RuntimeError('Невірний HTTPS URL')
    return base


def _encode(payload: dict) -> str:
    serialized=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return base64.b64encode(serialized).decode('ascii')


def signature(data: str, private_key: str) -> str:
    digest=hashlib.sha3_256((private_key+data+private_key).encode('utf-8')).digest()
    return base64.b64encode(digest).decode('ascii')


def checkout_fields(order) -> dict:
    pub,private=merchant_keys()
    base=callback_base_url()
    started=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    payload={
       'version': API_VERSION,'public_key':pub,'action':'subscribe',
       'amount': round(order["amount_minor"] / 100, 2),
       'currency':order['currency'],
       'description':'InterOsvit Premium TEST ONLY',
       'order_id':order['order_id'],
       'language':'uk',
       'subscribe':'1',
       'subscribe_date_start':started,
       'subscribe_periodicity':'month',
       'sandbox':'1',
       'result_url':base+'/premium-v2/return',
       'server_url':base+'/premium-v2/liqpay/callback',
    }
    data=_encode(payload)
    return {'action':CHECKOUT_URL,'data':data,'signature':signature(data,private)}


def decode_verified_callback(data: str, received_signature: str) -> dict:
    pub,private=merchant_keys()
    if not data or len(data)>32768 or not received_signature or len(received_signature)>256:
        raise ValueError('Некоректний callback')
    if not hmac.compare_digest(signature(data,private),received_signature):
        raise ValueError('Невірний підпис LiqPay')
    try:
        payload=json.loads(base64.b64decode(data,validate=True).decode('utf-8'))
    except (ValueError,UnicodeDecodeError,TypeError) as ex:
        raise ValueError('Некоректний callback JSON') from ex
    if not isinstance(payload,dict) or str(payload.get('public_key','')) != pub:
        raise ValueError('Невідповідний public_key')
    if str(payload.get('version','')) != str(API_VERSION):
        raise ValueError('Непідтримувана версія callback')
    return payload


def cancel_renewals(order_id: str) -> bool:
    """Request cancellation at PSP. Do not revoke locally on network failure."""
    pub,private=merchant_keys()
    payload={'version':API_VERSION,'public_key':pub,'action':'unsubscribe',
             'order_id':order_id}
    data=_encode(payload)
    req=Request(REQUEST_URL,
                data=urlencode({'data':data,'signature':signature(data,private)}).encode('utf-8'),
                headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
    with urlopen(req,timeout=10) as resp:
        response=json.loads(resp.read(65536))
    if not isinstance(response,dict):
        return False
    return str(response.get('status','')).lower() in {'success','unsubscribed'}
