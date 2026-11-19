"""Read-only preflight for an installed InterOsvit Flask project.

Does not import app.py, change SQLite rows, expose secrets, or call external APIs.
Run from C:\\InterOsvit with python final_readiness.py --target local|liqpay.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

ROOT = Path(__file__).resolve().parent
MANDATORY_FILES = (
    'app.py', 'database.py', 'interosvit.db',
    'gamification_store.py', 'gamification_routes.py',
    'premium_v2_routes.py', 'premium_v2_store.py', 'premium_v2_gateway.py',
    'interactive_routes.py', 'matching_routes.py',
    'true_false_mode.py', 'matching_mode.py',
    'templates/premium_v2.html', 'templates/gamification_progress.html',
)
OPTIONAL_FILES = (
    'liqpay_callback_relay.py', 'check_liqpay_sandbox.py',
    'question_editor_routes.py', 'question_editor_store.py',
    'tests/test_repeat_xp.py', 'tests/test_premium_v2.py',
    'tests/test_liqpay_sandbox_step2.py',
)
EXPECTED_TABLES = ('users', 'games', 'gamification_attempts',
                   'io_premium_orders', 'io_premium_events')


def read_env_file(path: Path) -> tuple[dict, list[str]]:
    if not path.exists():
        return {}, ['Файл .env відсутній']
    result = {}
    duplicates = []
    counts = Counter()
    # Parse with python-dotenv where available; duplicate detection independent.
    try:
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key = stripped.split('=', 1)[0].strip()
            if key.startswith('export '):
                key = key[7:].strip()
            if key:
                counts[key] += 1
        duplicates = [name for name, number in counts.items() if number > 1]
        if dotenv_values is not None:
            result = dict(dotenv_values(path))
        else:
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    result[k.strip()] = v.strip().strip('"').strip("'")
    except (OSError, UnicodeError) as exc:
        return {}, [f'Не вдалося прочитати .env: {type(exc).__name__}']
    return result, [f'Дубльований параметр .env: {k}' for k in duplicates]


def valid_https_base(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return (parts.scheme == 'https' and bool(parts.hostname)
                and parts.hostname.lower() not in {'127.0.0.1', 'localhost', '0.0.0.0'}
                and not parts.hostname.lower().endswith(('.local', '.example'))
                and parts.path in ('', '/') and not parts.query and not parts.fragment
                and parts.username is None and parts.password is None
                and parts.port in (None, 443))
    except ValueError:
        return False


class Check:
    def __init__(self):
        self.items = []

    def add(self, level: str, code: str, message: str):
        assert level in {'PASS', 'WARN', 'FAIL'}
        self.items.append({'level': level, 'code': code, 'message': message})
        print(f'[{level:4}] {message}')

    def results(self):
        counts = Counter(x['level'] for x in self.items)
        return {'passed': counts['PASS'], 'warnings': counts['WARN'],
                'failed': counts['FAIL']}


def source_check(ck: Check, target: str):
    missing = [str(p) for p in MANDATORY_FILES if not (ROOT / p).is_file()]
    if missing:
        for missing_path in missing:
            ck.add('FAIL', 'file_missing', f'Немає робочого файлу: {missing_path}')
    else:
        ck.add('PASS', 'sources_exist', 'Основні модулі та шаблони знайдено')
    for rel in OPTIONAL_FILES:
        if not (ROOT / rel).is_file():
            ck.add('WARN', 'optional_file', f'Немає допоміжного файлу: {rel}')
    for py in sorted(ROOT.glob('*.py')):
        if py.name.startswith(('install_', 'migrate_', 'fix_')):
            continue
        try:
            ast.parse(py.read_text(encoding='utf-8-sig'), filename=py.name)
        except (SyntaxError, OSError, UnicodeError) as error:
            ck.add('FAIL', 'syntax', f'Помилка синтаксису або читання {py.name}: {type(error).__name__}')
    if (ROOT / 'app.py').is_file():
        code = (ROOT / 'app.py').read_text(encoding='utf-8-sig')
        if 'premium_v2_bp' not in code or 'register_blueprint' not in code:
            ck.add('FAIL', 'premium_blueprint', 'Premium v2 не зареєстрований в app.py')
        else:
            ck.add('PASS', 'premium_blueprint', 'Premium v2 зареєстрований в app.py')
        if 'print(\n    "PREMIUM DEBUG:"' in code or 'PREMIUM DEBUG:' in code:
            ck.add('WARN', 'debug', 'Знайдено тимчасовий PREMIUM DEBUG у app.py')
    routes = ROOT / 'premium_v2_routes.py'
    if routes.is_file():
        text = routes.read_text(encoding='utf-8-sig')
        if 'def liqpay_developer_only' not in text:
            ck.add('WARN', 'liqpay_scope', 'Не видно обмеження LiqPay для DEV_USER_ID — перевір інсталятор кроку 2')
        else:
            ck.add('PASS', 'liqpay_scope', 'Перевірка DEV_USER_ID для LiqPay Sandbox є в маршрутах')
        if 'PREMIUM DEBUG:' in text:
            ck.add('WARN', 'debug', 'Прибери тимчасовий PREMIUM DEBUG з premium_v2_routes.py')
    if target == 'liqpay' and not (ROOT / 'liqpay_callback_relay.py').is_file():
        ck.add('FAIL', 'missing_relay', 'Для LiqPay необхідний liqpay_callback_relay.py')


def database_check(ck: Check, env: dict):
    db_name = str(env.get('INTEROSVIT_DB_PATH') or 'interosvit.db')
    db = Path(db_name)
    if not db.is_absolute():
        db = ROOT / db
    if not db.is_file():
        ck.add('FAIL', 'database_missing', 'Файл бази даних не знайдено')
        return
    try:
        # SQLite URI mode=ro never writes to the database.
        uri = db.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            state = conn.execute('PRAGMA integrity_check(1)').fetchone()[0]
            if state != 'ok':
                ck.add('FAIL', 'db_integrity', 'PRAGMA integrity_check виявив проблему')
            else:
                ck.add('PASS', 'db_integrity', 'SQLite: перевірка цілісності пройдена (read-only)')
            tables = {row[0] for row in conn.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            for table in EXPECTED_TABLES:
                if table not in tables:
                    ck.add('FAIL', 'db_schema', f'Відсутня таблиця {table}; не запускай повторні міграції навмання')
            if 'users' in tables:
                user_id = str(env.get('DEV_USER_ID') or '').strip()
                if not user_id.isdecimal():
                    ck.add('FAIL', 'dev_user_id', 'DEV_USER_ID має бути числом, наприклад 3')
                else:
                    found = conn.execute('SELECT 1 FROM users WHERE id=?', (int(user_id),)).fetchone()
                    ck.add('PASS' if found else 'FAIL', 'dev_user_exists',
                           'DEV_USER_ID існує в users' if found else 'DEV_USER_ID не існує в users')
            if {'io_premium_orders', 'users'} <= tables:
                premium = conn.execute('SELECT COUNT(*) FROM io_premium_orders').fetchone()[0]
                ck.add('PASS', 'premium_data', f'Тестова історія підписок доступна (замовлень: {premium})')
    except (sqlite3.Error, OSError, ValueError) as error:
        ck.add('FAIL', 'database_error', f'Помилка читання SQLite: {type(error).__name__}')


def configuration_check(ck: Check, env: dict, duplicates: list[str], target: str):
    for item in duplicates:
        ck.add('WARN', 'dotenv_duplicate', item)
    expected = {
        'APP_ENV': 'development',
        'SUBSCRIPTIONS_TEST_MODE': 'true',
        'ENABLE_DEMO_PREMIUM': 'false',
    }
    for key, wanted in expected.items():
        current = str(env.get(key) or '').strip().lower()
        ck.add('PASS' if current == wanted else 'FAIL', 'env',
               f'{key}: {wanted} (OK)' if current == wanted else f'{key}: потрібне {wanted}')
    provider = str(env.get('SUBSCRIPTIONS_TEST_PROVIDER') or '').strip().lower()
    if provider != target:
        ck.add('FAIL', 'provider', f'Для цього запуску потрібне SUBSCRIPTIONS_TEST_PROVIDER={target}; зараз {provider or "порожньо"}')
    else:
        ck.add('PASS', 'provider', f'Активний лише тестовий провайдер: {provider}')
    if target == 'liqpay':
        pub = str(env.get('LIQPAY_PUBLIC_KEY') or '').strip()
        secret = str(env.get('LIQPAY_PRIVATE_KEY') or '').strip()
        placeholders = ('...', 'ваш', 'your', 'example', 'xxx', 'test_private_key')
        valid = (pub.startswith('sandbox_') and secret.startswith('sandbox_')
                 and len(pub) >= 14 and len(secret) >= 20
                 and not any(word in pub.lower() or word in secret.lower() for word in placeholders))
        ck.add('PASS' if valid else 'FAIL', 'keys',
               'Обидва тестові ключі схожі на ключі Sandbox (значення приховано)' if valid
               else 'Потрібні видані LiqPay тестові ключі; приклади sandbox_... не працюють')
        base = str(env.get('PREMIUM_V2_PUBLIC_BASE_URL') or '')
        ck.add('PASS' if valid_https_base(base) else 'FAIL', 'callback_url',
               'Зовнішня HTTPS-адреса callback налаштована (адресу приховано)' if valid_https_base(base)
               else 'PREMIUM_V2_PUBLIC_BASE_URL: потрібна діюча зовнішня HTTPS-адреса з HTTPS тунелю')
        ck.add('WARN', 'external_unverified',
               'Перевірка формату не доводить, що LiqPay реально надіслав callback або пройшло автопродовження')
    else:
        ck.add('PASS', 'local_provider',
               'Local: відсутність ключів LiqPay не блокує внутрішній фінальний тест')
        ck.add('WARN', 'external_unverified', 'LiqPay Sandbox ще не засвідчено реальними тестовими callback')


def smoke_check(ck: Check):
    base = 'http://127.0.0.1:5000'
    for path in ('/pricing', '/premium-v2', '/my-progress'):
        try:
            req = Request(base + path, method='GET')
            with urlopen(req, timeout=4) as resp:
                status = resp.status
        except HTTPError as err:
            status = err.code
            err.close()
        except (URLError, TimeoutError, OSError):
            ck.add('WARN', 'smoke_offline', f'{path}: Flask недоступний на localhost:5000')
            continue
        # Protected endpoints may redirect to login without a session.
        ck.add('PASS' if status in (200, 302, 303) else 'FAIL', 'smoke',
               f'HTTP {status} для {path}' + (' (редирект на вхід допустимий)' if status in (302, 303) else ''))


def main(argv=None):
    parser = argparse.ArgumentParser(description='InterOsvit final read-only checks')
    parser.add_argument('--target', choices=['local', 'liqpay'], default='local',
                        help='Тестований провайдер підписок')
    parser.add_argument('--smoke', action='store_true', help='Перевірити HTTP маршрути на localhost:5000')
    args = parser.parse_args(argv)
    ck = Check()
    print('=== INTEROSVIT: КОНТРОЛЬНА ПЕРЕВІРКА (БЕЗ ЗМІН БД) ===')
    print('Ціль:', args.target)
    env, duplicates = read_env_file(ROOT / '.env')
    source_check(ck, args.target)
    configuration_check(ck, env, duplicates, args.target)
    database_check(ck, env)
    if args.smoke:
        smoke_check(ck)
    else:
        ck.add('WARN', 'smoke_not_run', 'HTTP-перевірку не запускали; додай --smoke коли Flask працює')
    summary = ck.results()
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'mode': args.target,
        'summary': summary,
        'checks': ck.items,
        'notes': [
            'Звіт не підтверджує реальний зв’язок із LiqPay, лише конфігурацію та локальний стан.',
            'Жодні секретні ключі або їх значення не включено.',
            'Фінальний запуск unittest виконується окремо; результати потрібно додати до лабораторної.',
        ],
    }
    directory = ROOT / 'reports'
    directory.mkdir(exist_ok=True)
    file = directory / 'final_readiness.json'
    file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nРезультат:', summary)
    print('Збережено без секретів:', file.relative_to(ROOT))
    return 1 if summary['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
