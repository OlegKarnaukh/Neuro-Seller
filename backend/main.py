"""
Neuro-Seller FastAPI Application
"""
import subprocess
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, engine
from app.api.v1 import api_router
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    print(f"🚀 Starting {settings.APP_NAME} v{settings.VERSION}")
    print(f"📊 Environment: {settings.ENVIRONMENT}")
    
    try:
        # Запускаем миграции Alembic
        logger.info("🔄 Запуск миграций базы данных...")
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app/backend",
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            logger.info("✅ Миграции применены успешно")
            print("✅ Миграции применены успешно")
        else:
            logger.error(f"❌ Ошибка миграций: {result.stderr}")
            print(f"❌ Ошибка миграций: {result.stderr}")
        
        # Инициализируем БД (создаём таблицы, если их нет)
        init_db()
        print("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        print(f"❌ Database initialization failed: {e}")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": f"{settings.APP_NAME} API",
        "version": settings.VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }


@app.get("/debug/db-schema")
async def get_db_schema():
    """Получить схему таблицы users"""
    query = text("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns 
        WHERE table_name = 'users'
        ORDER BY ordinal_position;
    """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2],
                    "default": row[3]
                }
                for row in result
            ]
        
        return {"table": "users", "columns": columns}
    except Exception as e:
        return {"error": str(e)}
