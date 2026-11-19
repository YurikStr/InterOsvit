"""Run ONLY in development, after backup_database.py. No real payment setup."""
import argparse
import os
from premium_v2_store import db_path,migrate

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--reset-demo-premium', action='store_true',
                        help='Reset demo Premium accounts to Free; saves old plans in io_premium_legacy_plans')
    args=parser.parse_args()
    if os.getenv('APP_ENV','development').lower()!='development':
        raise SystemExit('Міграція цього тестового пакета дозволена лише в development')
    print('База даних:',db_path())
    info=migrate(reset_legacy_demo=args.reset_demo_premium)
    print('OK: таблиці Premium v2 створено; старі ігри й XP не змінено.')
    print('Демо Premium -> Free:',info['reset_demo_count'])
