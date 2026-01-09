from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
from dotenv import load_dotenv

from ai_client import AIClient
from agents import AgentManager
from database import Database

load_dotenv()

app = FastAPI(title="Нейропродавец API", version="1.0.0")

# CORS для Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация
db = Database(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./neuro_seller.db"))
agent_manager = AgentManager(db)

# Модели данных
class ConstructorMessage(BaseModel):
    user_id: str
    message: str
    files: Optional[List[str]] = []

class TestAgentMessage(BaseModel):
    agent_id: str
    message: str

class SaveAgentRequest(BaseModel):
    agent_id: str

# Startup
@app.on_event("startup")
async def startup():
    """Инициализация БД при запуске"""
    await db.init_db()
    print("✅ Database initialized")

# API Endpoints
@app.post("/api/constructor-chat")
async def constructor_chat(data: ConstructorMessage):
    """Диалог с конструктором агента"""
    try:
        result = await agent_manager.handle_constructor_message(
            user_id=data.user_id,
            message=data.message,
            files=data.files
        )
        return result
    except Exception as e:
        print(f"❌ Error in constructor_chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test-agent")
async def test_agent(data: TestAgentMessage):
    """Тестирование созданного агента"""
    try:
        result = await agent_manager.test_agent(
            agent_id=data.agent_id,
            message=data.message
        )
        return result
    except Exception as e:
        print(f"❌ Error in test_agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-agent")
async def save_agent(data: SaveAgentRequest):
    """Сохранение и активация агента"""
    try:
        result = await agent_manager.save_agent(data.agent_id)
        return result
    except Exception as e:
        print(f"❌ Error in save_agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents/{user_id}")
async def get_user_agents(user_id: str):
    """Получить все агенты пользователя"""
    try:
        agents = await agent_manager.get_user_agents(user_id)
        return {"agents": agents}
    except Exception as e:
        print(f"❌ Error in get_user_agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Проверка работоспособности"""
    return {"status": "ok", "service": "neuro-seller-api", "version": "1.0.0"}

@app.get("/")
async def root():
    """Корневой маршрут"""
    return {
        "message": "Нейропродавец API",
        "docs": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
