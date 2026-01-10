"""
Database configuration and session management
"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for getting database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database - create tables if they don't exist
    """
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database initialized")
    
    # Применяем миграции (добавляем недостающие поля)
    apply_migrations()


def apply_migrations():
    """
    Применяет необходимые миграции к БД
    (добавляет новые поля, если их нет)
    """
    try:
        with engine.connect() as conn:
            # Проверяем, есть ли поле avatar_url в таблице agents
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agents' 
                  AND column_name = 'avatar_url';
            """))
            
            if not result.fetchone():
                # Поле не найдено — добавляем
                logger.info("🔧 Добавляем поле avatar_url в таблицу agents...")
                conn.execute(text("""
                    ALTER TABLE agents 
                    ADD COLUMN avatar_url TEXT DEFAULT NULL;
                """))
                conn.commit()
                logger.info("✅ Поле avatar_url успешно добавлено!")
            else:
                logger.info("✅ Поле avatar_url уже существует")
    
    except Exception as e:
        logger.error(f"❌ Ошибка при применении миграций: {e}")
        # Не падаем, если миграция не удалась (возможно, поле уже есть)
