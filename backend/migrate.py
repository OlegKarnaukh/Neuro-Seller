"""
Скрипт для запуска миграций Alembic
"""
import os
import sys
from alembic.config import Config
from alembic import command

# Добавляем путь к backend
sys.path.insert(0, os.path.dirname(__file__))

def run_migrations():
    """Запускает все pending миграции"""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("✅ Миграции выполнены успешно!")

if __name__ == "__main__":
    run_migrations()
