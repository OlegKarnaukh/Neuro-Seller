"""
API для конструктора AI агентов
"""
import logging
import re
import json
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

# Добавляем путь к модулям
sys.path.insert(0, '/app/backend')

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User, PlanType
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt
from app.services.openai_service import chat_completion, parse_agent_ready_response

# Настройка логирования
logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory хранилище диалогов (для демо)
conversations: Dict[str, List[Dict[str, str]]] = {}


# Pydantic модели
class Message(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[Message]


class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool = False
    agent_updated: bool = False
    agent_id: Optional[str] = None


# Вспомогательные функции
def parse_website(text: str) -> List[str]:
    """Извлекает URL из текста"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return [url.rstrip('.,!?;:)') for url in urls]


def extract_info_from_website(url: str) -> Dict[str, Any]:
    """
    Извлекает информацию с сайта через OpenAI
    """
    try:
        logger.info(f"🌐 Парсинг сайта: {url}")
        
        prompt = f"""Изучи содержимое сайта {url} и извлеки следующую информацию в формате JSON:

{{
  "business_type": "тип бизнеса",
  "services": [
    {{"name": "название услуги", "price": "цена"}}
  ],
  "about": "краткое описание компании",
  "contacts": "контактная информация"
}}

Если какая-то информация недоступна, используй пустую строку или пустой массив."""

        response = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.3
        )
        
        # Извлекаем JSON из ответа
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            data = json.loads(json_str)
            logger.info(f"✅ Информация с сайта успешно извлечена")
            return data
        else:
            logger.warning(f"⚠️ Не удалось извлечь JSON из ответа")
            return {}
            
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге сайта: {e}")
        return {}


def merge_knowledge_bases(existing: Dict, new: Dict) -> Dict:
    """Объединяет две базы знаний"""
    merged = existing.copy()
    
    # Объединяем services
    if "services" in new:
        if "services" not in merged:
            merged["services"] = []
        merged["services"].extend(new["services"])
    
    # Обновляем остальные поля
    for key in ["about", "contacts", "business_type"]:
        if key in new and new[key]:
            merged[key] = new[key]
    
    return merged


# Основной эндпоинт
@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Диалог с мета-агентом для создания агента-продавца
    """
    try:
        user_id = request.user_id
        
        # Создаём пользователя, если не существует
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = User(
                id=user_id,
                telegram_id=None,
                plan_type=PlanType.FREE,
                plan_expires_at=None
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"✅ Создан новый пользователь: {user_id}")
        
        # Загружаем историю диалога
        if user_id not in conversations:
            conversations[user_id] = []
        
        conversation = conversations[user_id]
        
        # Добавляем новые сообщения из запроса
        for msg in request.messages:
            # Проверяем, что сообщение не дублируется
            if not conversation or conversation[-1]["content"] != msg.content:
                conversation.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Парсим URL из последнего сообщения пользователя
        last_user_message = None
        for msg in reversed(request.messages):
            if msg.role == "user":
                last_user_message = msg.content
                break
        
        site_info = None
        if last_user_message:
            urls = parse_website(last_user_message)
            if urls:
                url = urls[0]
                logger.info(f"🌐 Найден URL: {url}")
                site_info = extract_info_from_website(url)
                
                if site_info:
                    # Добавляем информацию с сайта в контекст
                    system_message = f"[СИСТЕМА: Изучил сайт {url}.\nСодержимое:\n{json.dumps(site_info, ensure_ascii=False, indent=2)}]"
                    conversation.append({
                        "role": "system",
                        "content": system_message
                    })
        
        # Формируем контекст для мета-агента
        context = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ]
        context.extend(conversation)
        
        # Отправляем запрос к OpenAI
        assistant_response = chat_completion(
            messages=context,
            model="gpt-4o-mini",
            temperature=0.7
        )
        
        # Добавляем ответ ассистента в историю
        conversation.append({
            "role": "assistant",
            "content": assistant_response
        })
        
        # Проверяем, готов ли агент
        agent_data = parse_agent_ready_response(assistant_response)
        
        if agent_data:
            logger.info(f"✅ Создаём агента...")
            
            agent_name = agent_data["agent_name"]
            business_type = agent_data["business_type"]
            kb_dict = agent_data["knowledge_base"]
            
            # Генерируем system_prompt (передаём kb_dict как словарь)
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=kb_dict
            )
            
            # Определяем персону (victoria или alexander)
            persona_name = "victoria" if "виктория" in agent_name.lower() else "alexander"
            
            # Проверяем, есть ли уже агент у пользователя
            existing_agent = db.query(Agent).filter(
                Agent.user_id == user_id
            ).first()
            
            if existing_agent:
                # Обновляем существующего агента
                existing_agent.agent_name = agent_name
                existing_agent.business_type = business_type
                existing_agent.persona = persona_name  # ✅ короткое имя (victoria/alexander)
                existing_agent.system_prompt = system_prompt  # ✅ длинный промпт
                existing_agent.knowledge_base = kb_dict
                existing_agent.status = "active"
                existing_agent.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"✅ Агент обновлён! ID: {existing_agent.id}")
                
                return ConstructorChatResponse(
                    response=f"🎉 Отлично! Агент '{agent_name}' обновлён!",
                    agent_created=False,
                    agent_updated=True,
                    agent_id=str(existing_agent.id)
                )
            else:
                # Создаём нового агента
                new_agent = Agent(
                    id=uuid4(),
                    user_id=user_id,
                    agent_name=agent_name,
                    business_type=business_type,
                    persona=persona_name,  # ✅ короткое имя (victoria/alexander)
                    system_prompt=system_prompt,  # ✅ длинный промпт
                    knowledge_base=kb_dict,
                    status="active",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_agent)
                db.commit()
                db.refresh(new_agent)
                
                logger.info(f"✅ Агент создан! ID: {new_agent.id}")
                
                # Очищаем историю диалога
                conversations[user_id] = []
                
                return ConstructorChatResponse(
                    response=f"🎉 Отлично! Агент '{agent_name}' создан!",
                    agent_created=True,
                    agent_updated=False,
                    agent_id=str(new_agent.id)
                )
        
        # Если агент не готов, возвращаем обычный ответ
        return ConstructorChatResponse(
            response=assistant_response,
            agent_created=False,
            agent_updated=False,
            agent_id=None
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в constructor_chat: {e}")
        logger.error(f"Traceback: ", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
