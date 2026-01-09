from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
from openai import OpenAI
from prompts import META_AGENT_PROMPT, generate_seller_prompt
import re
import uuid
import requests
from bs4 import BeautifulSoup

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
agents = {}

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
    files = data.files
    
    # Инициализация истории диалога
    if user_id not in conversations:
        conversations[user_id] = {
            "history": [],
            "agent_data": {},
            "agent_id": None,
            "collected_info": {
                "business_type": "",
                "services": [],
                "website_content": "",
                "objections": []
            }
        }
    
    collected = conversations[user_id]["collected_info"]
    
    # Обработка файлов (если есть)
    if files:
        for file_url in files:
            try:
                file_content = extract_file_content(file_url)
                collected["services"].append(f"Из файла: {file_content}")
            except Exception as e:
                pass
    
    # Обработка ссылок в сообщении
    urls = extract_urls(message)
    website_info = ""
    
    if urls:
        for url in urls:
            try:
                site_content = parse_website(url)
                collected["website_content"] = site_content
                website_info = f"\n\n[СИСТЕМА: Изучил сайт {url}. Содержимое:\n{site_content[:1000]}...]"
            except Exception as e:
                website_info = f"\n\n[СИСТЕМА: Ошибка чтения сайта {url}: {str(e)}]"
    
    # Добавляем информацию о сайте к сообщению пользователя
    user_message_with_context = message
    if website_info:
        user_message_with_context += website_info
    
    # Добавляем сообщение в историю
    conversations[user_id]["history"].append({
        "role": "user",
        "content": user_message_with_context
    })
    
    # Формируем контекст для OpenAI
    messages = [
        {"role": "system", "content": META_AGENT_PROMPT}
    ] + conversations[user_id]["history"]
    
    try:
        # Вызов OpenAI API
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=1200
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
            
            # Генерируем уникальный agent_id
            agent_id = str(uuid.uuid4())
            
            # Сохраняем связь
            conversations[user_id]["agent_data"] = agent_data
            conversations[user_id]["agent_id"] = agent_id
            
            # Сохраняем агента
            agents[agent_id] = {
                "agent_data": agent_data,
                "test_history": [],
                "created_by": user_id
            }
            
            # УБИРАЕМ ВСЕ ТЕГИ ИЗ ТЕКСТА
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
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/test-agent")
def test_agent(data: AgentTest):
    """Тестирование созданного агента"""
    
    agent_id = data.agent_id
    message = data.message
    
    if agent_id in agents:
        agent_data = agents[agent_id]["agent_data"]
        test_history = agents[agent_id]["test_history"]
    elif agent_id in conversations and conversations[agent_id].get("agent_data"):
        agent_data = conversations[agent_id]["agent_data"]
        if "test_history" not in conversations[agent_id]:
            conversations[agent_id]["test_history"] = []
        test_history = conversations[agent_id]["test_history"]
    else:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    seller_prompt = generate_seller_prompt(
        agent_name=agent_data.get("agent_name", "Виктория"),
        business_type=agent_data.get("business_type", ""),
        knowledge_base=agent_data.get("knowledge_base", "")
    )
    
    test_history.append({
        "role": "user",
        "content": message
    })
    
    messages = [
        {"role": "system", "content": seller_prompt}
    ] + test_history
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        assistant_message = response.choices[0].message.content
        
        test_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return {
            "response": assistant_message,
            "agent_name": agent_data.get("agent_name", "Виктория"),
            "status": "success"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@app.post("/api/save-agent")
def save_agent(data: AgentSave):
    """Сохранение финализированного агента"""
    
    agent_id = data.agent_id
    
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent_data = agents[agent_id]["agent_data"]
    
    return {
        "status": "success",
        "message": "Agent saved successfully",
        "agent_id": agent_id,
        "agent_data": agent_data
    }

def extract_agent_data(message: str) -> dict:
    """Извлекает данные агента из финального сообщения"""
    
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
    """Убирает ВСЕ технические теги из сообщения"""
    
    # Удаляем все возможные варианты тегов
    clean = message
    
    # Вариант 1: [AGENT_READY]
    clean = re.sub(r'\[AGENT_READY\]', '', clean, flags=re.IGNORECASE)
    
    # Вариант 2: [AGENT_NAME: ...]
    clean = re.sub(r'\[AGENT_NAME:.*?\]', '', clean, flags=re.IGNORECASE)
    
    # Вариант 3: [BUSINESS_TYPE: ...]
    clean = re.sub(r'\[BUSINESS_TYPE:.*?\]', '', clean, flags=re.IGNORECASE)
    
    # Вариант 4: [KNOWLEDGE_BASE: ...]
    clean = re.sub(r'\[KNOWLEDGE_BASE:.*?\]', '', clean, flags=re.IGNORECASE)
    
    # Вариант 5: [ТЕГИ: ...]
    clean = re.sub(r'\[ТЕГИ:.*?\]', '', clean, flags=re.IGNORECASE | re.DOTALL)
    
    # Вариант 6: Любые теги в квадратных скобках с "AGENT", "BUSINESS", "KNOWLEDGE"
    clean = re.sub(r'\[.*?(AGENT|BUSINESS|KNOWLEDGE|ТЕГ).*?\]', '', clean, flags=re.IGNORECASE | re.DOTALL)
    
    # Убираем лишние пустые строки
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    
    return clean.strip()

def extract_urls(text: str) -> List[str]:
    """Извлекает URL из текста"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)

def parse_website(url: str) -> str:
    """Парсит сайт и извлекает текстовую информацию"""
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Удаляем скрипты, стили, навигацию
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        
        # Извлекаем текст
        text = soup.get_text()
        
        # Очищаем текст
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Ограничиваем длину
        return text[:4000]
        
    except Exception as e:
        raise Exception(f"Ошибка парсинга сайта: {str(e)}")

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
