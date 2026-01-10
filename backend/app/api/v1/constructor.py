"""
Constructor API - Meta-agent for creating seller agents
"""
import json
import re
import logging
import httpx
from typing import List, Dict, Optional, Any
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from bs4 import BeautifulSoup

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User, PlanType
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt
from app.services.openai_service import chat_completion, parse_agent_ready_response

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Хранилище для истории диалогов (в памяти)
conversations: Dict[str, List[Dict[str, str]]] = {}


# ============================================================================
# МОДЕЛИ PYDANTIC
# ============================================================================

class Message(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    agent_id: Optional[str] = None
    messages: List[Dict[str, str]]


class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool
    agent_updated: bool
    agent_id: Optional[str] = None


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def parse_website(url: str) -> Dict[str, Any]:
    """
    Парсит сайт и возвращает его содержимое.
    """
    try:
        logger.info(f"🌐 Парсинг сайта: {url}")
        
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.decompose()
        
        title = soup.find('title')
        title_text = title.get_text().strip() if title else ""
        
        description = soup.find('meta', attrs={'name': 'description'})
        description_text = description.get('content', '').strip() if description else ""
        
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        content = text[:3000] if len(text) > 3000 else text
        
        logger.info(f"✅ Сайт успешно спарсен: {title_text}")
        
        return {
            "success": True,
            "url": url,
            "title": title_text,
            "description": description_text,
            "content": content
        }
    
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге сайта: {e}")
        return {"success": False, "url": url, "error": str(e)}


def extract_info_from_website(url: str) -> Dict[str, Any]:
    """
    Извлекает структурированную информацию с сайта через GPT.
    """
    
    site_data = parse_website(url)
    
    if not site_data["success"]:
        logger.error(f"❌ Не удалось спарсить сайт: {url}")
        return {}
    
    prompt = f"""
Проанализируй содержимое сайта и извлеки следующую информацию в формате JSON:

{{
  "business_type": "тип бизнеса",
  "services": [
    {{"name": "название услуги", "price": "цена"}}
  ],
  "about": "описание бизнеса",
  "contacts": {{
    "phone": "телефон",
    "email": "email",
    "address": "адрес"
  }}
}}

ВАЖНО: Верни только JSON, без текста.

Содержимое сайта:
{site_data["content"][:3000]}
"""
    
    response = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        temperature=0.3
    )
    
    logger.info(f"📝 Ответ GPT: {response[:200]}")
    
    try:
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        
        if json_start == -1 or json_end <= json_start:
            logger.error("❌ JSON не найден")
            return {}
        
        json_str = response[json_start:json_end]
        site_info = json.loads(json_str)
        
        logger.info(f"✅ Информация извлечена: {list(site_info.keys())}")
        return site_info
    
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return {}


def merge_knowledge_bases(old_kb: Dict[str, Any], new_kb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Объединяет две базы знаний.
    """
    merged = old_kb.copy()
    
    if "services" in new_kb:
        if "services" not in merged:
            merged["services"] = []
        
        existing_names = {s.get("name", "").lower() for s in merged["services"]}
        
        for service in new_kb["services"]:
            if service.get("name", "").lower() not in existing_names:
                merged["services"].append(service)
    
    for key in ["about", "contacts", "website", "additional_info"]:
        if key in new_kb:
            merged[key] = new_kb[key]
    
    return merged


# ============================================================================
# API ЭНДПОИНТ
# ============================================================================

@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для общения с мета-агентом конструктора.
    
    Поддерживает:
    - Создание нового агента
    - Обновление существующего агента
    - Парсинг сайтов для извлечения информации
    """
    
    try:
        user_id = request.user_id
        agent_id = request.agent_id
        new_messages = request.messages
        
        # 1. ПРОВЕРКА/СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            logger.info(f"👤 Создаём пользователя {user_id}")
            
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
            
            logger.info(f"✅ Пользователь создан")
        
        # 2. ЗАГРУЗКА ИСТОРИИ ДИАЛОГА
        conversation_key = f"{user_id}:{agent_id}" if agent_id else user_id
        
        if conversation_key not in conversations:
            conversations[conversation_key] = []
        
        conversations[conversation_key].extend(new_messages)
        
        # 3. ПАРСИНГ САЙТА (если есть URL)
        if new_messages:
            last_message = new_messages[-1].get("content", "")
            urls = re.findall(r'https?://[^\s]+', last_message)
            
            if urls:
                site_url = urls[0]
                logger.info(f"🌐 Найден URL: {site_url}")
                
                site_data = parse_website(site_url)
                
                if site_data["success"]:
                    site_info = extract_info_from_website(site_url)
                    
                    if site_info:
                        site_context = f"""
[ИНФОРМАЦИЯ С САЙТА {site_url}]
{json.dumps(site_info, ensure_ascii=False, indent=2)}
[КОНЕЦ ИНФОРМАЦИИ]
"""
                        conversations[conversation_key].append({
                            "role": "system",
                            "content": site_context
                        })
                        logger.info("✅ Информация с сайта добавлена")
        
        # 4. ФОРМИРОВАНИЕ КОНТЕКСТА
        context = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ] + conversations[conversation_key]
        
        # 5. ВЫЗОВ OPENAI
        assistant_response = chat_completion(
            messages=context,
            model="gpt-4o-mini",
            temperature=0.7
        )
        
        # 6. ОБРАБОТКА СОЗДАНИЯ АГЕНТА
        agent_data = parse_agent_ready_response(assistant_response)
        
        if agent_data:
            logger.info("✅ Создаём агента...")
            
            new_agent = Agent(
                id=uuid4(),
                user_id=user_id,
                agent_name=agent_data["agent_name"],
                business_type=agent_data["business_type"],
                persona="Victoria",
                knowledge_base=agent_data["knowledge_base"],
                system_prompt=generate_seller_prompt(
                    agent_name=agent_data["agent_name"],
                    business_type=agent_data["business_type"],
                    knowledge_base=agent_data["knowledge_base"],
                    persona="Victoria"
                ),
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)
            
            logger.info(f"✅ Агент создан! ID={new_agent.id}")
            
            conversations[conversation_key] = []
            
            return ConstructorChatResponse(
                response=f"🎉 Агент '{new_agent.agent_name}' создан!",
                agent_created=True,
                agent_updated=False,
                agent_id=str(new_agent.id)
            )
        
        # 7. ОБЫЧНЫЙ ОТВЕТ
        conversations[conversation_key].append({
            "role": "assistant",
            "content": assistant_response
        })
        
        return ConstructorChatResponse(
            response=assistant_response,
            agent_created=False,
            agent_updated=False,
            agent_id=None
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
