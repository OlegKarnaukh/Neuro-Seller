from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
from openai import OpenAI
from prompts import META_AGENT_PROMPT, generate_seller_prompt
from database import Database
import re
import uuid
import requests
from bs4 import BeautifulSoup
import logging
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# ... остальные импорты ...

app = FastAPI(title="Neuro-Seller API", version="1.0.0")

# Добавьте ЭТИ СТРОКИ:
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    # Вернуть HTML вместо JSON
    return FileResponse("static/index.html")


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Neuro-Seller API", version="1.0.0")

# CORS для Base44
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.base44.com", "https://*.base44.com", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI клиент
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agents.db")
db = Database(DATABASE_URL)

# Временное хранилище для конструктора
conversations = {}

# Модели данных
class Message(BaseModel):
    user_id: str
    message: str
    files: List[str] = []

class AgentTest(BaseModel):
    agent_id: str
    message: str

class AgentSave(BaseModel):
    agent_id: str

@app.on_event("startup")
async def startup():
    """Инициализация БД при запуске"""
    await db.init_db()
    logger.info("✅ Database initialized")
    logger.info(f"📝 META_AGENT_PROMPT version: {META_AGENT_PROMPT[:100]}...")

@app.get("/")
def read_root():
    return {
        "message": "Neuro-Seller API is running! 🚀",
        "version": "2.0",
        "endpoints": {
            "health": "/health",
            "constructor": "/api/constructor-chat",
            "test_agent": "/api/test-agent",
            "save_agent": "/api/save-agent",
            "get_agents": "/api/agents/{user_id}"
        }
    }

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "neuro-seller-api",
        "version": "2.0",
        "database": "connected"
    }

@app.post("/api/constructor-chat")
def constructor_chat(data: Message):
    """Конструктор агента - диалог с мета-агентом"""
    
    user_id = data.user_id
    message = data.message
    files = data.files
    
    logger.info(f"📩 Constructor chat: user_id={user_id}, message={message[:100]}")
    
    # Инициализация истории
    if user_id not in conversations:
        conversations[user_id] = {
            "history": [],
            "agent_data": {},
            "agent_id": None
        }
    
    # Обработка файлов
    if files:
        logger.info(f"📎 Processing {len(files)} files")
        for file_url in files:
            try:
                file_content = extract_file_content(file_url)
                message += f"\n\n[СИСТЕМА: Содержимое файла:\n{file_content[:1000]}...]"
                logger.info(f"✅ File processed: {file_url[:50]}")
            except Exception as e:
                logger.error(f"❌ File error: {e}")
    
    # Обработка ссылок
    urls = extract_urls(message)
    if urls:
        logger.info(f"🔗 Found {len(urls)} URLs: {urls}")
        for url in urls:
            try:
                logger.info(f"🌐 Parsing website: {url}")
                site_content = parse_website(url)
                message += f"\n\n[СИСТЕМА: Изучил сайт {url}. Содержимое:\n{site_content[:2000]}...]"
                logger.info(f"✅ Website parsed successfully. Content length: {len(site_content)}")
            except Exception as e:
                logger.error(f"❌ Website parse error: {e}")
                message += f"\n\n[СИСТЕМА: Ошибка чтения сайта {url}: {str(e)}]"
    
    # Добавляем в историю
    conversations[user_id]["history"].append({
        "role": "user",
        "content": message
    })
    
    logger.info(f"📊 History length: {len(conversations[user_id]['history'])}")
    
    # Контекст для OpenAI
    messages = [
        {"role": "system", "content": META_AGENT_PROMPT}
    ] + conversations[user_id]["history"]
    
    try:
        # Вызов OpenAI
        logger.info("🤖 Calling OpenAI API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=1200
        )
        
        assistant_message = response.choices[0].message.content
        logger.info(f"✅ OpenAI response received. Length: {len(assistant_message)}")
        logger.info(f"📝 Response preview: {assistant_message[:200]}")
        
        conversations[user_id]["history"].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        # Проверка финализации
        if "[AGENT_READY]" in assistant_message:
            logger.info("🎉 Agent ready! Extracting data...")
            
            # Извлекаем данные
            agent_data = extract_agent_data(assistant_message)
            logger.info(f"📊 Extracted agent_data: {agent_data}")
            
            # Генерируем промпт продавца
            seller_prompt = generate_seller_prompt(
                agent_name=agent_data.get("agent_name", "Виктория"),
                business_type=agent_data.get("business_type", ""),
                knowledge_base=agent_data.get("knowledge_base", "")
            )
            
            logger.info(f"📝 Generated seller_prompt length: {len(seller_prompt)}")
            logger.info(f"📝 Seller prompt preview: {seller_prompt[:300]}")
            
            # СОХРАНЯЕМ В БАЗУ ДАННЫХ
            import asyncio
            agent_id = asyncio.run(db.create_agent(
                user_id=user_id,
                agent_name=agent_data.get("agent_name", ""),
                business_type=agent_data.get("business_type", ""),
                knowledge_base=agent_data.get("knowledge_base", ""),
                system_prompt=seller_prompt
            ))
            
            logger.info(f"💾 Agent saved to DB: {agent_id}")
            
            conversations[user_id]["agent_data"] = agent_data
            conversations[user_id]["agent_id"] = agent_id
            
            # Убираем теги
            clean_message = remove_tags(assistant_message)
            
            return {
                "response": clean_message,
                "status": "agent_ready",
                "agent_id": agent_id,
                "agent_data": agent_data
            }
        
        return {
            "response": assistant_message,
            "status": "in_progress"
        }
        
    except Exception as e:
        logger.error(f"❌ OpenAI API error: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/test-agent")
async def test_agent(data: AgentTest):
    """Тестирование агента"""
    
    agent_id = data.agent_id
    message = data.message
    
    logger.info(f"🧪 Testing agent: {agent_id}, message: {message[:100]}")
    
    # ПОЛУЧАЕМ АГЕНТА ИЗ БАЗЫ ДАННЫХ
    agent = await db.get_agent(agent_id)
    
    if not agent:
        logger.error(f"❌ Agent not found: {agent_id}")
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    logger.info(f"✅ Agent loaded: {agent['agent_name']}")
    logger.info(f"📝 System prompt preview: {agent['system_prompt'][:300]}")
    
    # Инициализируем историю тестирования
    if agent_id not in conversations:
        conversations[agent_id] = {"test_history": []}
    
    conversations[agent_id]["test_history"].append({
        "role": "user",
        "content": message
    })
    
    # Формируем контекст
    messages = [
        {"role": "system", "content": agent["system_prompt"]}
    ] + conversations[agent_id]["test_history"]
    
    try:
        logger.info("🤖 Calling OpenAI for agent test...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        assistant_message = response.choices[0].message.content
        logger.info(f"✅ Agent response: {assistant_message[:200]}")
        
        conversations[agent_id]["test_history"].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        # Сохраняем в БД
        await db.save_conversation(
            agent_id=agent_id,
            channel="preview",
            messages=conversations[agent_id]["test_history"]
        )
        
        return {
            "response": assistant_message,
            "agent_name": agent["agent_name"],
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"❌ OpenAI API error during test: {e}")
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/save-agent")
async def save_agent(data: AgentSave):
    """Сохранение агента"""
    
    agent_id = data.agent_id
    
    agent = await db.get_agent(agent_id)
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    await db.update_agent_status(agent_id, "active")
    
    logger.info(f"✅ Agent activated: {agent_id}")
    
    return {
        "status": "success",
        "message": "Agent activated successfully",
        "agent_id": agent_id
    }

@app.get("/api/agents/{user_id}")
async def get_user_agents(user_id: str):
    """Получить всех агентов пользователя"""
    
    agents = await db.get_user_agents(user_id)
    
    return {
        "status": "success",
        "count": len(agents),
        "agents": agents
    }

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def extract_agent_data(message: str) -> dict:
    """Извлекает данные агента"""
    
    agent_data = {}
    
    if "[AGENT_NAME:" in message:
        start = message.find("[AGENT_NAME:") + len("[AGENT_NAME:")
        end = message.find("]", start)
        agent_data["agent_name"] = message[start:end].strip()
    
    if "[BUSINESS_TYPE:" in message:
        start = message.find("[BUSINESS_TYPE:") + len("[BUSINESS_TYPE:")
        end = message.find("]", start)
        agent_data["business_type"] = message[start:end].strip()
    
    if "[KNOWLEDGE_BASE:" in message:
        start = message.find("[KNOWLEDGE_BASE:") + len("[KNOWLEDGE_BASE:")
        end = message.find("]", start)
        agent_data["knowledge_base"] = message[start:end].strip()
    
    return agent_data

def remove_tags(message: str) -> str:
    """Убирает теги"""
    
    clean = message
    clean = re.sub(r'\[AGENT_READY\]', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[AGENT_NAME:.*?\]', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[BUSINESS_TYPE:.*?\]', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\[KNOWLEDGE_BASE:.*?\]', '', clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r'\[ТЕГИ:.*?\]', '', clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r'\[.*?(AGENT|BUSINESS|KNOWLEDGE|ТЕГ).*?\]', '', clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    
    return clean.strip()

def extract_urls(text: str) -> List[str]:
    """Извлекает URL"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)

def parse_website(url: str) -> str:
    """Парсит сайт"""
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text[:4000]
        
    except Exception as e:
        raise Exception(f"Ошибка парсинга: {str(e)}")

def extract_file_content(file_url: str) -> str:
    """Извлекает содержимое файла"""
    
    try:
        response = requests.get(file_url, timeout=10)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '')
        
        if 'text' in content_type or 'json' in content_type:
            return response.text[:3000]
        else:
            return f"[Файл типа {content_type}]"
            
    except Exception as e:
        raise Exception(f"Ошибка чтения файла: {str(e)}")
