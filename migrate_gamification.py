"""Safe, repeatable migration for InterOsvit gamification."""
from gamification_store import db_path, migrate

if __name__ == '__main__':
    print('База даних:', db_path())
    info = migrate()
    if info['already_migrated']:
        print('OK: структуру вже встановлено. Наявні результати не дубльовано.')
    else:
        print('OK: таблиці гейміфікації створено.')
        print('Перенесено попередніх проходжень:', info['imported'])
        print('Для старих проходжень серію правильних відповідей не можна відновити.')
