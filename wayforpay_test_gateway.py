"""One-time, shared test-merchant checkout ONLY. Never accepts live credentials.

Documentation: https://wiki.wayforpay.com/en/view/852102
Published test details: https://wiki.wayforpay.com/en/view/852472
This shared public secret MUST NOT be used to grant real subscriptions.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import os
import re
from urllib.parse import urlsplit

TEST_ACCOUNT = 'test_merch_n1'
# Published in official WayForPay sandbox documentation (not a private merchant key).
TEST_SECRET = 'flk3409refn54t54t*FNJRET'
PAY_URL = 'https://secure.wayforpay.com/pay'
PRODUCT = 'InterOsvit Premium - test only'


def sandbox_guard() -> None:
    if os.getenv('APP_ENV', '').strip().lower() != 'development':
        raise RuntimeError('WayForPay test is allowed only with APP_ENV=development')
    if os.getenv('SUBSCRIPTIONS_TEST_MODE', '').strip().lower() != 'true':
        raise RuntimeError('WayForPay test requires SUBSCRIPTIONS_TEST_MODE=true')
    if os.getenv('WAYFORPAY_TEST_MODE', '').strip().lower() != 'true':
        raise RuntimeError('WayForPay test requires WAYFORPAY_TEST_MODE=true')
    if os.getenv('SUBSCRIPTIONS_TEST_PROVIDER', '').strip().lower() != 'local':
        raise RuntimeError('Keep Premium v2 on local while running the isolated WayForPay test')


def public_base() -> str:
    base = os.getenv('PREMIUM_V2_PUBLIC_BASE_URL', '').strip().rstrip('/')
    url = urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise RuntimeError('PREMIUM_V2_PUBLIC_BASE_URL must be a public HTTPS origin without a path')
    if url.hostname in ('localhost', '127.0.0.1', '::1') or url.hostname.endswith('.local'):
        raise RuntimeError('A public HTTPS hostname is required')
    return base


def hmac_md5(items) -> str:
    raw = ';'.join(str(x) for x in items)
    return hmac.new(TEST_SECRET.encode('utf-8'), raw.encode('utf-8'), hashlib.md5).hexdigest()


def amount_string(minor: int) -> str:
    return f'{minor // 100}.{minor % 100:02d}'


def purchase_fields(order) -> dict:
    sandbox_guard()
    base = public_base()
    domain = urlsplit(base).hostname
    order_ref = order['order_ref']
    amount = amount_string(order['amount_minor'])
    items = [TEST_ACCOUNT, domain, order_ref, str(order['order_date']), amount,
             order['currency'], PRODUCT, '1', amount]
    return {
        'merchantAccount': TEST_ACCOUNT,
        'merchantAuthType': 'SimpleSignature',
        'merchantDomainName': domain,
        'merchantTransactionSecureType': 'AUTO',
        'merchantSignature': hmac_md5(items),
        'apiVersion': '1',
        'language': 'UA',
        'orderReference': order_ref,
        'orderDate': str(order['order_date']),
        'amount': amount,
        'currency': order['currency'],
        'productName[]': PRODUCT,
        'productPrice[]': amount,
        'productCount[]': '1',
        'regularMode': 'none',  # intentionally NOT recurring / no payment credentials saved
        'returnUrl': base+'/wayforpay-test/return',
        'serviceUrl': base+'/wayforpay-test/callback',
    }


def minor_from_amount(value) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError('missing amount')
    try:
        d=Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('invalid amount') from None
    if not d.is_finite() or d < 0 or d.as_tuple().exponent < -2:
        raise ValueError('invalid amount precision')
    cents=d*100
    if cents != cents.to_integral_value():
        raise ValueError('invalid amount precision')
    return int(cents)


def verify_callback(payload: dict) -> None:
    sandbox_guard()
    required=('merchantAccount','orderReference','amount','currency','authCode',
              'cardPan','transactionStatus','reasonCode','merchantSignature')
    if not isinstance(payload,dict) or any(k not in payload for k in required):
        raise ValueError('missing WayForPay callback fields')
    if payload.get('merchantAccount') != TEST_ACCOUNT:
        raise ValueError('wrong merchant')
    if not isinstance(payload.get('orderReference'),str) or not re.fullmatch(r'wfptest_[A-Za-z0-9_-]{12,48}',payload['orderReference']):
        raise ValueError('wrong order format')
    supplied=payload['merchantSignature']
    if not isinstance(supplied,str) or not re.fullmatch(r'[0-9a-fA-F]{32}',supplied):
        raise ValueError('invalid signature format')
    sig = hmac_md5(payload[field] for field in required[:-1])
    if not hmac.compare_digest(sig.lower(), supplied.lower()):
        raise ValueError('bad WayForPay callback signature')


def acknowledgment(order_ref: str, now: int) -> dict:
    return {'orderReference':order_ref,'status':'accept','time':now,
            'signature':hmac_md5((order_ref,'accept',now))}
