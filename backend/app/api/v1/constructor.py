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
    response: Optional[str] = None
    status: Optional[str] = None
    agent_id: Optional[str] = None
    agent_data: Optional[AgentData] = None


def format_uuid(user_id: str) -> str:
    """Форматирует строку в валидный UUID формат."""
    clean_id = user_id.replace('-', '')
    
    if len(clean_id) < 32:
        clean_id = clean_id.ljust(32, '0')
    
    if len(clean_id) > 32:
        clean_id = clean_id[:32]
    
    formatted = f"{clean_id[0:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:32]}"
    
    try:
        UUID(formatted)
        return formatted
    except ValueError:
        logger.warning(f"⚠️ Не удалось сформатировать UUID из '{user_id}', создаём новый")
        return str(uuid4())


def parse_website(text: str) -> List[str]:
    """Извлекает URL из текста"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return [url.rstrip('.,!?;:)') for url in urls]


def extract_info_from_website(url: str) -> Dict[str, Any]:
    """Извлекает информацию с сайта (временно отключено)"""
    logger.info(f"🌐 Парсинг сайта отключён: {url}")
    return {}


@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """Конструктор агентов через диалог с мета-агентом"""
    try:
        # Конвертируем user_id в валидный UUID
        user_id = format_uuid(request.user_id)
        logger.info(f"🔄 Конструктор: user_id = {user_id}")

        # Проверяем существование пользователя
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            logger.info(f"👤 Создаём нового пользователя: {user_id}")
            new_user = User(
                id=user_id,
                plan="free"  # ✅ Убрали telegram_id
            )
            db.add(new_user)
            db.commit()
            logger.info(f"✅ Пользователь создан: {user_id}")

        
        # История диалога
        if user_id not in conversations:
            conversations[user_id] = []
        
        conversation = conversations[user_id]
        
        # Добавляем новые сообщения
        for msg in request.messages:
            if not conversation or conversation[-1]["content"] != msg.content:
                conversation.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Парсим URL (временно отключено)
        last_user_message = None
        for msg in reversed(request.messages):
            if msg.role == "user":
                last_user_message = msg.content
                break
        
        if last_user_message:
            urls = parse_website(last_user_message)
            if urls:
                logger.info(f"🌐 Найден URL: {urls[0]} (парсинг отключён)")
        
        # Формируем контекст
        context = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ]
        context.extend(conversation)
        
        # Отправляем в OpenAI
        assistant_response = await chat_completion(
            messages=context,
            model="gpt-4o-mini",
            temperature=0.7
        )
        
        # Добавляем ответ
        conversation.append({
            "role": "assistant",
            "content": assistant_response
        })
        
        # Проверяем готовность агента
        agent_data = parse_agent_ready_response(assistant_response)
        
        if agent_data:
            logger.info(f"✅ Создаём агента...")
            
            agent_name = agent_data["agent_name"]
            business_type = agent_data["business_type"]
            kb_dict = agent_data["knowledge_base"]
            
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=kb_dict
            )
            
            persona_name = "victoria" if "виктория" in agent_name.lower() else "alexander"
            
            existing_agent = db.query(Agent).filter(
                Agent.user_id == user_id
            ).first()
            
            if existing_agent:
                existing_agent.agent_name = agent_name
                existing_agent.business_type = business_type
                existing_agent.persona = persona_name
                existing_agent.system_prompt = system_prompt
                existing_agent.knowledge_base = kb_dict
                existing_agent.status = "draft"
                existing_agent.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"✅ Агент обновлён! ID: {existing_agent.id}")
                
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
                
                conversations[user_id] = []
                
                return ConstructorChatResponse(
                    status="agent_ready",
                    agent_id=str(new_agent.id),
                    agent_data=AgentData(
                        agent_name=agent_name,
                        business_type=business_type,
                        knowledge_base=kb_dict
                    )
                )
        
        return ConstructorChatResponse(
            response=assistant_response
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в constructor_chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
