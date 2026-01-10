"""
API для конструктора AI агентов
"""
import logging
import re
import json
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

sys.path.insert(0, '/app/backend')

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User, PlanType
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt
from app.services.openai_service import chat_completion, parse_agent_ready_response

logger = logging.getLogger(__name__)

router = APIRouter()

conversations: Dict[str, List[Dict[str, str]]] = {}


# Pydantic модели
class Message(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[Message]


class AgentData(BaseModel):
    """Данные агента для Base44"""
    agent_name: str
    business_type: str
    knowledge_base: Dict[str, Any]


class ConstructorChatResponse(BaseModel):
    """
    Base44 Integration Response Format
    """
    response: Optional[str] = None
    status: Optional[str] = None
    agent_id: Optional[str] = None
    agent_data: Optional[AgentData] = None


# ✅ Функция для форматирования user_id в валидный UUID
def format_uuid(user_id: str) -> str:
    """
    Форматирует строку в валидный UUID формат.
    
    Примеры:
    - "69611ae203d0641b357eee82" → "69611ae2-03d0-641b-357e-ee82xxxxxxxx"
    - "550e8400e29b41d4a716446655440000" → "550e8400-e29b-41d4-a716-446655440000"
    """
    # Убираем все дефисы
    clean_id = user_id.replace('-', '')
    
    # Если меньше 32 символов, дополняем нулями
    if len(clean_id) < 32:
        clean_id = clean_id.ljust(32, '0')
    
    # Если больше 32, обрезаем
    if len(clean_id) > 32:
        clean_id = clean_id[:32]
    
    # Форматируем в UUID: 8-4-4-4-12
    formatted = f"{clean_id[0:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:32]}"
    
    try:
        # Проверяем, что это валидный UUID
        UUID(formatted)
        return formatted
    except ValueError:
        # Если не получилось, генерируем новый
        logger.warning(f"⚠️ Не удалось сформатировать UUID из '{user_id}', создаём новый")
        return str(uuid4())


# Вспомогательные функции
def parse_website(text: str) -> List[str]:
    """Извлекает URL из текста"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return [url.rstrip('.,!?;:)') for url in urls]


def extract_info_from_website(url: str) -> Dict[str, Any]:
    """Извлекает информацию с сайта через OpenAI"""
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

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.3
        )
        
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


@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Диалог с мета-агентом для создания агента-продавца.
    
    Base44 Integration:
    - Входной формат: {"user_id": "...", "messages": [...]}
    - Выходной формат (агент готов): {"status": "agent_ready", "agent_id": "...", "agent_data": {...}}
    - Выходной формат (обычный): {"response": "..."}
    """
    try:
        # ✅ Форматируем user_id в валидный UUID
        user_id_raw = request.user_id
        user_id = format_uuid(user_id_raw)
        
        logger.info(f"📝 user_id получен: '{user_id_raw}' → форматирован: '{user_id}'")
        
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
        assistant_response = await chat_completion(
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
            
            # Генерируем system_prompt
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=kb_dict
            )
            
            # Определяем персону
            persona_name = "victoria" if "виктория" in agent_name.lower() else "alexander"
            
            # Проверяем, есть ли уже агент у пользователя
            existing_agent = db.query(Agent).filter(
                Agent.user_id == user_id
            ).first()
            
            if existing_agent:
                # Обновляем существующего агента
                existing_agent.agent_name = agent_name
                existing_agent.business_type = business_type
                existing_agent.persona = persona_name
                existing_agent.system_prompt = system_prompt
                existing_agent.knowledge_base = kb_dict
                existing_agent.status = "draft"
                existing_agent.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"✅ Агент обновлён! ID: {existing_agent.id}")
                
                # ✅ Base44 формат ответа
                return ConstructorChatResponse(
                    status="agent_ready",
                    agent_id=str(existing_agent.id),
                    agent_data=AgentData(
                        agent_name=agent_name,
                        business_type=business_type,
                        knowledge_base=kb_dict
                    )
                )
            else:
                # Создаём нового агента
                new_agent = Agent(
                    id=uuid4(),
                    user_id=user_id,
                    agent_name=agent_name,
                    business_type=business_type,
                    persona=persona_name,
                    system_prompt=system_prompt,
                    knowledge_base=kb_dict,
                    status="draft",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_agent)
                db.commit()
                db.refresh(new_agent)
                
                logger.info(f"✅ Агент создан! ID: {new_agent.id}")
                
                # Очищаем историю диалога
                conversations[user_id] = []
                
                # ✅ Base44 формат ответа
                return ConstructorChatResponse(
                    status="agent_ready",
                    agent_id=str(new_agent.id),
                    agent_data=AgentData(
                        agent_name=agent_name,
                        business_type=business_type,
                        knowledge_base=kb_dict
                    )
                )
        
        # Если агент не готов, возвращаем обычный ответ
        return ConstructorChatResponse(
            response=assistant_response
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в constructor_chat: {e}")
        logger.error(f"Traceback: ", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
