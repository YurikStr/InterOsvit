"""InterOsvit Premium v2: sandbox-only subscription state and SQLite accounting.

All state transitions (including changing users.plan) are atomic; no card data is stored.
Never trust a browser redirect or a client-supplied success flag to activate Premium.
"""
from __future__ import annotations

import calendar
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sqlite3

from dotenv import load_dotenv
load_dotenv()

PRICE_MINOR = 9900   # ILLUSTRATIVE TEST PRICE ONLY; not a commercial offer
CURRENCY = 'UAH'


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def parse_stamp(value: str) -> datetime:
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)


def add_month(start: datetime) -> datetime:
    """One calendar month, preserving time and clipping 31st to the last day."""
    target_year = start.year + (start.month == 12)
    target_month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, calendar.monthrange(target_year, target_month)[1])
    return start.replace(year=target_year, month=target_month, day=day)


def db_path() -> Path:
    configured = os.getenv('INTEROSVIT_DB_PATH', '').strip()
    path = Path(configured) if configured else Path(__file__).resolve().with_name('interosvit.db')
    if not path.is_file():
        raise RuntimeError(f'Базу InterOsvit не знайдено: {path}')
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 20000')
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    required = {'users': {'id', 'plan'}, 'games': {'id'}}
    for table, fields in required.items():
        names = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
        if not fields <= names:
            raise RuntimeError(f'Невідповідна структура таблиці {table}: {sorted(fields - names)}')


def migrate(reset_legacy_demo: bool = False) -> dict:
    """Idempotent schema migration. Optional explicit one-time demo-plan reset."""
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            ensure_tables(conn)
            conn.execute('''CREATE TABLE IF NOT EXISTS io_premium_orders (
                id INTEGER PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id),
                provider TEXT NOT NULL CHECK (provider IN ('local','liqpay')),
                status TEXT NOT NULL CHECK (status IN
                  ('pending','active','cancel_pending','canceled','failed','expired')),
                amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
                currency TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT,
                auto_renew INTEGER NOT NULL DEFAULT 1 CHECK(auto_renew IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_premium_user
                ON io_premium_orders(user_id,status,period_end)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS io_premium_events (
                event_key TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES io_premium_orders(order_id),
                provider_payment_id TEXT,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS io_premium_legacy_plans (
                user_id INTEGER PRIMARY KEY,
                previous_plan TEXT NOT NULL,
                captured_at TEXT NOT NULL
            )''')
            changed = 0
            if reset_legacy_demo:
                # Do not erase existing paid subscriptions if migration rerun.
                rows = conn.execute('''SELECT id,plan FROM users
                    WHERE plan='premium' AND NOT EXISTS (
                      SELECT 1 FROM io_premium_orders o
                      WHERE o.user_id=users.id AND o.status IN ('active','cancel_pending')
                        AND o.period_end > ?
                    )''', (stamp(utcnow()),)).fetchall()
                for user in rows:
                    conn.execute('''INSERT OR IGNORE INTO io_premium_legacy_plans
                        (user_id,previous_plan,captured_at) VALUES(?,?,?)''',
                        (user['id'],user['plan'],stamp(utcnow())))
                    conn.execute("UPDATE users SET plan='free' WHERE id=?", (user['id'],))
                    changed += 1
            conn.commit()
            return {'reset_demo_count': changed}
        except Exception:
            conn.rollback()
            raise


def latest_for_user(user_id: int):
    with closing(connect()) as conn:
        return conn.execute('''SELECT * FROM io_premium_orders
            WHERE user_id=? ORDER BY id DESC LIMIT 1''', (user_id,)).fetchone()


def by_order(order_id: str):
    with closing(connect()) as conn:
        return conn.execute('SELECT * FROM io_premium_orders WHERE order_id=?', (order_id,)).fetchone()


def create_order(user_id: int, provider: str):
    if provider not in {'local','liqpay'}:
        raise ValueError('Невідомий провайдер')
    now = stamp(utcnow())
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone() is None:
                raise ValueError('Користувача не знайдено')
            current = conn.execute('''SELECT * FROM io_premium_orders
                WHERE user_id=? AND status IN ('pending','active','cancel_pending')
                ORDER BY id DESC LIMIT 1''', (user_id,)).fetchone()
            if current is not None:
                if current['status'] == 'pending' or (current['period_end'] and current['period_end'] > now):
                    if current['provider'] != provider:
                        raise ValueError('Уже існує підписка іншого тестового провайдера')
                    conn.commit()
                    return current
                # stale row (app may have been offline), expire it atomically
                conn.execute('''UPDATE io_premium_orders SET status='expired',updated_at=?
                    WHERE id=?''', (now,current['id']))
            if conn.execute('''SELECT 1 FROM io_premium_orders WHERE user_id=?
                AND status IN ('active','cancel_pending') AND period_end>? LIMIT 1''', (user_id,now)).fetchone():
                raise ValueError('Premium уже активний')
            order_id = 'io2_' + secrets.token_urlsafe(18)
            conn.execute('''INSERT INTO io_premium_orders
              (order_id,user_id,provider,status,amount_minor,currency,auto_renew,created_at,updated_at)
              VALUES(?,?,?,'pending',?,?,1,?,?)''',
              (order_id,user_id,provider,PRICE_MINOR,CURRENCY,now,now))
            conn.commit()
            return conn.execute('SELECT * FROM io_premium_orders WHERE order_id=?',(order_id,)).fetchone()
        except Exception:
            conn.rollback()
            raise


def apply_event(order_id: str, event_key: str, status: str, action: str,
                provider_payment_id: str = '', now: datetime | None = None) -> str:
    """Only call after cryptographic gateway validation OR gated local simulation.

    Event id is unique and prevents replay. Unknown orders and mismatches are rejected.
    """
    now = now or utcnow()
    ts = stamp(now)
    if not isinstance(event_key,str) or not event_key or len(event_key)>160:
        raise ValueError('Невірний ідентифікатор події')
    if status not in {'approved','declined'} or action not in {'initial','renewal'}:
        raise ValueError('Невідомий статус події')
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            order = conn.execute('SELECT * FROM io_premium_orders WHERE order_id=?', (order_id,)).fetchone()
            if order is None:
                raise ValueError('Невідоме замовлення')
            if conn.execute('SELECT 1 FROM io_premium_events WHERE event_key=?',(event_key,)).fetchone():
                conn.commit()
                return 'duplicate'
            # Record even an ignored authenticated event to avoid replay mutation.
            conn.execute('''INSERT INTO io_premium_events
              (event_key,order_id,provider_payment_id,action,status,processed_at)
              VALUES(?,?,?,?,?,?)''',(event_key,order_id,provider_payment_id[:128],action,status,ts))
            outcome = 'ignored'
            if status=='approved' and action=='initial' and order['status']=='pending':
                expiry = stamp(add_month(now))
                conn.execute('''UPDATE io_premium_orders SET status='active',
                  period_start=?,period_end=?,updated_at=? WHERE id=?''',
                  (ts,expiry,ts,order['id']))
                conn.execute("UPDATE users SET plan='premium' WHERE id=?", (order['user_id'],))
                outcome='activated'
            elif status=='declined' and action=='initial' and order['status']=='pending':
                conn.execute("UPDATE io_premium_orders SET status='failed',updated_at=? WHERE id=?",(ts,order['id']))
                outcome='declined'
            elif status=='approved' and action=='renewal' and order['status']=='active' and order['auto_renew']:
                current_expiry=parse_stamp(order['period_end'])
                new_expiry=stamp(add_month(max(current_expiry, now)))
                conn.execute('''UPDATE io_premium_orders SET period_end=?,updated_at=? WHERE id=?''',
                  (new_expiry,ts,order['id']))
                conn.execute("UPDATE users SET plan='premium' WHERE id=?", (order['user_id'],))
                outcome='renewed'
            conn.commit()
            return outcome
        except Exception:
            conn.rollback()
            raise


def mark_cancelled(order_id: str, user_id: int, now: datetime | None = None) -> str:
    now = now or utcnow()
    ts = stamp(now)
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            o=conn.execute('SELECT * FROM io_premium_orders WHERE order_id=? AND user_id=?',
                           (order_id,user_id)).fetchone()
            if not o:
                raise ValueError('Підписку не знайдено')
            if o['status']=='pending':
                conn.execute("UPDATE io_premium_orders SET status='canceled',auto_renew=0,updated_at=? WHERE id=?",(ts,o['id']))
                result='canceled'
            elif o['status']=='active' and o['period_end']>ts:
                conn.execute('''UPDATE io_premium_orders SET status='cancel_pending',
                  auto_renew=0,updated_at=? WHERE id=?''',(ts,o['id']))
                result='cancel_pending'
            elif o['status']=='cancel_pending':
                result='cancel_pending'
            else:
                raise ValueError('Цю підписку вже завершено')
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def expire_due(now: datetime | None = None) -> int:
    now = now or utcnow()
    ts=stamp(now)
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            rows=conn.execute('''SELECT id,user_id FROM io_premium_orders
                WHERE status IN ('active','cancel_pending') AND period_end <= ?''', (ts,)).fetchall()
            if rows:
                conn.executemany('''UPDATE io_premium_orders SET status='expired',updated_at=?
                    WHERE id=?''', [(ts,r['id']) for r in rows])
                for user_id in {r['user_id'] for r in rows}:
                    other=conn.execute('''SELECT 1 FROM io_premium_orders WHERE user_id=?
                       AND status IN ('active','cancel_pending') AND period_end>? LIMIT 1''',(user_id,ts)).fetchone()
                    if other is None:
                        conn.execute("UPDATE users SET plan='free' WHERE id=?",(user_id,))
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback()
            raise


def force_expire_test(order_id: str, user_id: int) -> None:
    """DEV-ONLY; caller MUST enforce loopback and developer account checks."""
    with closing(connect()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor=conn.execute('''UPDATE io_premium_orders SET period_end=?,updated_at=?
                WHERE order_id=? AND user_id=? AND status IN ('active','cancel_pending')''',
                ('2000-01-01 00:00:00',stamp(utcnow()),order_id,user_id))
            if cursor.rowcount!=1:
                raise ValueError('Немає активної підписки для завершення')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
