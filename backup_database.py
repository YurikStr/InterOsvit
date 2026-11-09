import sqlite3
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "interosvit.db"
BACKUP_DIR = BASE_DIR / "backups"


def backup_database():
    if not DATABASE.exists():
        raise FileNotFoundError(
            "Файл interosvit.db не знайдено."
        )

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    backup_path = BACKUP_DIR / (
        f"interosvit_backup_{timestamp}.db"
    )

    source = sqlite3.connect(DATABASE)
    destination = sqlite3.connect(backup_path)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    print(
        "Резервну копію створено:",
        backup_path.name
    )


if __name__ == "__main__":
    backup_database()
