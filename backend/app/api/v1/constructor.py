"""
API для конструктора агентов
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional
import uuid
import re
from datetime import datetime
import json

from app.core.database import get_db
from app.models.user import User, PlanType
from app.models.agent import Agent
from app.services.openai_service import chat_completion, parse_agent_ready_response
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt

# Импорты для парсинга сайтов
import httpx
from bs4 import BeautifulSoup

router = APIRouter()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEMAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Message(BaseModel):
    role: str
    content: str

class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[Message]
    files: Optional[List[str]] = []  # URLs файлов
    
class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool
    agent_id: Optional[str] = None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ПАРСИНГ САЙТОВ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def parse_website(url: str) -> Dict:
    """
    Парсит сайт и извлекает информацию о бизнесе
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Извлекаем текст
        text = soup.get_text(separator=' ', strip=True)
        
        # Ограничиваем длину (первые 3000 символов)
        text = text[:3000]
        
        # Извлекаем заголовок
        title = soup.title.string if soup.title else ""
        
        # Извлекаем мета-описание
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        description = meta_desc['content'] if meta_desc and meta_desc.get('content') else ""
        
        return {
            "success": True,
            "url": url,
            "title": title,
            "description": description,
            "content": text
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

async def extract_info_from_website(url: str) -> Dict:
    """
    Парсит сайт и использует GPT для извлечения структурированной информации
    """
    parsed_data = await parse_website(url)
    
    if not parsed_data["success"]:
        return {"error": parsed_data["error"]}
    
    # Используем GPT для структурирования информации
    extraction_prompt = f"""Проанализируй содержимое сайта и извлеки структурированную информацию.

Сайт: {url}
Заголовок: {parsed_data['title']}
Описание: {parsed_data['description']}

Содержимое:
{parsed_data['content']}

Извлеки и структурируй:
1. Тип бизнеса (чем занимается компания)
2. Услуги/товары (список)
3. Цены (если есть)
4. Контакты (телефон, email, адрес)
5. Краткое описание компании

Верни результат СТРОГО в формате JSON:
{{
  "business_type": "...",
  "services": ["...", "..."],
  "prices": {{"название": "цена", ...}},
  "contacts": {{"phone": "...", "email": "...", "address": "..."}},
  "about": "..."
}}

ВАЖНО: Верни только JSON, без дополнительного текста.
"""
    
    try:
        response = await chat_completion(
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.3
        )
        
        # Пытаемся извлечь JSON из ответа
        content = response["content"]
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            extracted_data = json.loads(json_match.group(0))
            extracted_data["website"] = url
            return extracted_data
        else:
            return {"raw_data": content, "website": url}
    
    except Exception as e:
        return {"error": f"Ошибка извлечения данных: {str(e)}", "website": url}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IN-MEMORY STORAGE для истории диалогов
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

conversations: Dict[str, List[Dict]] = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Диалог с мета-агентом для создания персонализированного агента
    """
    try:
        user_id = request.user_id
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем/создаём пользователя
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            # Создаём нового пользователя автоматически
            user = User(
                id=user_id,
                email=f"{user_id}@neuro-seller.local",
                plan=PlanType.FREE,
                credits_balance=1000,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
            print(f"✅ Created new user: {user_id}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Загружаем историю диалога
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        if user_id not in conversations:
            conversations[user_id] = []
        
        # Обрабатываем новые сообщения
        for msg in request.messages:
            msg_dict = msg.dict()
            if msg_dict not in conversations[user_id]:
                conversations[user_id].append(msg_dict)
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем наличие URL в последнем сообщении
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        last_message = request.messages[-1].content if request.messages else ""
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, last_message)
        
        # Если найден URL, парсим сайт
        if urls:
            url = urls[0]
            print(f"🔍 Парсинг сайта: {url}")
            
            website_data = await extract_info_from_website(url)
            
            # Добавляем информацию о сайте в контекст
            if "error" not in website_data:
                site_info_message = f"""[ИНФОРМАЦИЯ С САЙТА {url}]

Тип бизнеса: {website_data.get('business_type', 'не определено')}

Услуги/Товары:
{', '.join(website_data.get('services', []))}

Цены:
{json.dumps(website_data.get('prices', {}), ensure_ascii=False, indent=2)}

Контакты:
{json.dumps(website_data.get('contacts', {}), ensure_ascii=False, indent=2)}

О компании:
{website_data.get('about', '')}

[КОНЕЦ ИНФОРМАЦИИ С САЙТА]
"""
                conversations[user_id].append({
                    "role": "system",
                    "content": site_info_message
                })
                
                print(f"✅ Сайт успешно обработан")
            else:
                print(f"❌ Ошибка парсинга сайта: {website_data.get('error')}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Формируем контекст для GPT
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        messages = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ] + conversations[user_id]
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Запрос к OpenAI
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        response = await chat_completion(messages=messages, temperature=0.7)
        response_text = response["content"]
        
        print(f"📨 Ответ мета-агента: {response_text[:200]}...")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем, готов ли агент к созданию
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        agent_data = parse_agent_ready_response(response_text)
        
        if agent_data:
            print(f"🎉 Создаём агента: {agent_data}")
            
            # Создаём агента
            agent_name = agent_data["agent_name"]
            business_type = agent_data["business_type"]
            knowledge_base = agent_data["knowledge_base"]
            
            # Генерируем промпт для агента
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=knowledge_base
            )
            
            # Сохраняем агента в БД
            new_agent = Agent(
                id=str(uuid.uuid4()),
                user_id=user_id,
                agent_name=agent_name.capitalize(),
                business_type=business_type,
                persona=agent_name,
                knowledge_base=knowledge_base,
                system_prompt=system_prompt,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)
            
            print(f"✅ Агент создан с ID: {new_agent.id}")
            
            # Очищаем историю диалога
            conversations[user_id] = []
            
            return ConstructorChatResponse(
                response=f"🎉 Агент '{agent_name.capitalize()}' успешно создан!\n\nID агента: {new_agent.id}\n\nТеперь вы можете протестировать его работу или подключить к каналам (Telegram, WhatsApp, VK).",
                agent_created=True,
                agent_id=new_agent.id
            )
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Сохраняем ответ ассистента в историю
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        conversations[user_id].append({
            "role": "assistant",
            "content": response_text
        })
        
        return ConstructorChatResponse(
            response=response_text,
            agent_created=False,
            agent_id=None
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка в constructor_chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
