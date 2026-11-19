"""Isolated sandbox-only record-keeping. Does NOT modify InterOsvit users or plans."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time

DB_FILE='wayforpay_sandbox.db'
PRICE_MINOR=9900
CURRENCY='UAH'


def db_path() -> Path:
    override=os.getenv('WAYFORPAY_TEST_DB_PATH')
    return Path(override).resolve() if override else Path(__file__).resolve().with_name(DB_FILE)


def connect():
    cn=sqlite3.connect(str(db_path()),timeout=10)
    cn.row_factory=sqlite3.Row
    cn.execute('PRAGMA busy_timeout=10000')
    return cn


def ensure_schema():
    with closing(connect()) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS wfp_test_orders (
          order_ref TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
          order_date INTEGER NOT NULL, amount_minor INTEGER NOT NULL,
          currency TEXT NOT NULL, status TEXT NOT NULL,
          event_digest TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS ix_wfp_test_user ON wfp_test_orders(user_id,order_date)')
        c.commit()


def latest(user_id:int):
    ensure_schema()
    with closing(connect()) as c:
        return c.execute('SELECT * FROM wfp_test_orders WHERE user_id=? ORDER BY order_date DESC, rowid DESC LIMIT 1', (user_id,)).fetchone()


def get(order_ref:str):
    ensure_schema()
    with closing(connect()) as c:
        return c.execute('SELECT * FROM wfp_test_orders WHERE order_ref=?', (order_ref,)).fetchone()


def new_order(user_id:int):
    ensure_schema()
    if not isinstance(user_id,int) or user_id<1:
        raise ValueError('invalid user')
    now=int(time.time())
    ts=datetime.now(timezone.utc).isoformat(timespec='seconds')
    ref='wfptest_'+secrets.token_urlsafe(18)
    with closing(connect()) as c:
        c.execute('''INSERT INTO wfp_test_orders
             (order_ref,user_id,order_date,amount_minor,currency,status,created_at,updated_at)
             VALUES(?,?,?,?,?,'pending',?,?)''', (ref,user_id,now,PRICE_MINOR,CURRENCY,ts,ts))
        c.commit()
    return get(ref)


def apply_verified_callback(payload:dict):
    """Caller must first verify the gateway HMAC, amount, currency, account and order."""
    order_ref=payload['orderReference']
    event_digest=hashlib.sha256(('wfp:'+order_ref+':'+payload['merchantSignature']).encode('ascii')).hexdigest()
    new_status={'Approved':'approved','Declined':'declined','Expired':'declined',
                'Refunded':'declined','Voided':'declined'}.get(payload.get('transactionStatus'))
    ts=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with closing(connect()) as c:
        try:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM wfp_test_orders WHERE order_ref=?',(order_ref,)).fetchone()
            if old is None:
                raise ValueError('unknown test order')
            if old['status'] != 'pending' or not new_status:
                c.commit()
                return 'duplicate' if old['event_digest']==event_digest else 'ignored'
            # Test-only: never grant Premium. One-time paid/declined response tracking.
            c.execute('UPDATE wfp_test_orders SET status=?,event_digest=?,updated_at=? WHERE order_ref=?',
                      (new_status,event_digest,ts,order_ref))
            c.commit()
            return new_status
        except Exception:
            c.rollback()
            raise
