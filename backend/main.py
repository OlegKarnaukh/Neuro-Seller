from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
from openai import OpenAI
from prompts import META_AGENT_PROMPT, generate_seller_prompt
import re

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

# Хранилище диалогов (в памяти, для MVP)
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

@app.get("/")
def read_root():
    return {
        "message": "Neuro-Seller API is running! 🚀",
        "endpoints": {
            "health": "/health",
            "constructor": "/api/constructor-chat",
            "test_agent": "/api/test-agent",
            "save_agent": "/api/save-agent"
        }
    }

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "neuro-seller-api",
        "version": "1.0.0"
    }

@app.post("/api/constructor-chat")
def constructor_chat(data: Message):
    """Конструктор агента - диалог с мета-агентом"""
    
    user_id = data.user_id
    message = data.message
    
    # Инициализация истории диалога
    if user_id not in conversations:
        conversations[user_id] = {
            "history": [],
            "agent_data": {}
        }
    
    # Добавляем сообщение пользователя в историю
    conversations[user_id]["history"].append({
        "role": "user",
        "content": message
    })
    
    # Формируем полный контекст для OpenAI
    messages = [
        {"role": "system", "content": META_AGENT_PROMPT}
    ] + conversations[user_id]["history"]
    
    try:
        # Вызов OpenAI API
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        
        assistant_message = response.choices[0].message.content
        
        # Добавляем ответ ассистента в историю
        conversations[user_id]["history"].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        # Проверка на наличие тегов финализации
        if "[AGENT_READY]" in assistant_message:
            # Извлекаем данные агента из тегов
            agent_data = extract_agent_data(assistant_message)
            conversations[user_id]["agent_data"] = agent_data
            
            # УБИРАЕМ ТЕГИ ИЗ ТЕКСТА ДЛЯ ПОЛЬЗОВАТЕЛЯ
            clean_message = remove_tags(assistant_message)
            
            return {
                "response": clean_message,
                "status": "agent_ready",
                "agent_data": agent_data
            }
        
        return {
            "response": assistant_message,
            "status": "in_progress"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/test-agent")
def test_agent(data: AgentTest):
    """Тестирование созданного агента"""
    
    agent_id = data.agent_id
    message = data.message
    
    # Получаем данные агента из conversations
    # (в реальной версии — из БД)
    if agent_id not in conversations:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent_data = conversations[agent_id].get("agent_data", {})
    
    if not agent_data:
        raise HTTPException(status_code=400, detail="Agent not finalized")
    
    # Генерируем промпт продавца
    seller_prompt = generate_seller_prompt(
        agent_name=agent_data.get("agent_name", "Виктория"),
        business_type=agent_data.get("business_type", ""),
        knowledge_base=agent_data.get("knowledge_base", "")
    )
    
    # Инициализация истории тестирования
    if "test_history" not in conversations[agent_id]:
        conversations[agent_id]["test_history"] = []
    
    conversations[agent_id]["test_history"].append({
        "role": "user",
        "content": message
    })
    
    messages = [
        {"role": "system", "content": seller_prompt}
    ] + conversations[agent_id]["test_history"]
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        assistant_message = response.choices[0].message.content
        
        conversations[agent_id]["test_history"].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return {
            "response": assistant_message,
            "agent_name": agent_data.get("agent_name", "Виктория")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/save-agent")
def save_agent(data: AgentSave):
    """Сохранение финализированного агента"""
    
    agent_id = data.agent_id
    
    if agent_id not in conversations:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent_data = conversations[agent_id].get("agent_data", {})
    
    if not agent_data:
        raise HTTPException(status_code=400, detail="Agent not finalized")
    
    # В реальной версии: сохранение в БД
    # Сейчас просто возвращаем подтверждение
    
    return {
        "status": "success",
        "message": "Agent saved successfully",
        "agent_id": agent_id,
        "agent_data": agent_data
    }

def extract_agent_data(message: str) -> dict:
    """Извлекает данные агента из финального сообщения"""
    
    agent_data = {}
    
    # Извлечение AGENT_NAME
    if "[AGENT_NAME:" in message:
        start = message.find("[AGENT_NAME:") + len("[AGENT_NAME:")
        end = message.find("]", start)
        agent_data["agent_name"] = message[start:end].strip()
    
    # Извлечение BUSINESS_TYPE
    if "[BUSINESS_TYPE:" in message:
        start = message.find("[BUSINESS_TYPE:") + len("[BUSINESS_TYPE:")
        end = message.find("]", start)
        agent_data["business_type"] = message[start:end].strip()
    
    # Извлечение KNOWLEDGE_BASE
    if "[KNOWLEDGE_BASE:" in message:
        start = message.find("[KNOWLEDGE_BASE:") + len("[KNOWLEDGE_BASE:")
        end = message.find("]", start)
        agent_data["knowledge_base"] = message[start:end].strip()
    
    return agent_data

def remove_tags(message: str) -> str:
    """Убирает технические теги из сообщения"""
    
    # Удаляем все теги в квадратных скобках
    clean = re.sub(r'\[AGENT_READY\]', '', message)
    clean = re.sub(r'\[AGENT_NAME:.*?\]', '', clean)
    clean = re.sub(r'\[BUSINESS_TYPE:.*?\]', '', clean)
    clean = re.sub(r'\[KNOWLEDGE_BASE:.*?\]', '', clean)
    
    # Убираем лишние пустые строки
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    
    return clean.strip()
