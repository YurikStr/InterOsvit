"""CLI task to expire overdue sandbox subscriptions (safe to rerun)."""
import os
from premium_v2_gateway import only_test_environment
from premium_v2_store import expire_due

if __name__=='__main__':
    if not only_test_environment():
        raise SystemExit('Синхронізація Premium v2 дозволена лише у тестовому режимі')
    print('Завершено прострочених тестових підписок:',expire_due())
