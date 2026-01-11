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
from app.models.user import User
from app.models.constructor_conversation import ConstructorConversation
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt
from app.services.openai_service import chat_completion, parse_agent_ready_response, parse_agent_update_response

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic модели
class Message(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[Message]
    conversation_id: Optional[str] = None  # ✅ Новое поле


class AgentData(BaseModel):
    """Данные агента для Base44"""
    agent_name: str
    business_type: str
    description: str  # ← Добавлено
    instructions: str  # ← Добавлено
    knowledge_base: Dict[str, Any]


class ConstructorChatResponse(BaseModel):
    response: Optional[str] = None
    status: Optional[str] = None
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None  # ✅ Новое поле
    agent_data: Optional[AgentData] = None


class ConstructorHistoryResponse(BaseModel):
    """История диалога с конструктором"""
    messages: List[Message]


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


@router.get("/conversations/{user_id}")
async def get_user_conversations(
    user_id: str,
    db: Session = Depends(get_db)
):
    """
    Получить все constructor conversations пользователя.
    
    Возвращает список всех диалогов с мета-агентом и связанных агентов.
    """
    try:
        user_id = format_uuid(user_id)
        
        conversations = db.query(ConstructorConversation).filter(
            ConstructorConversation.user_id == user_id
        ).order_by(ConstructorConversation.updated_at.desc()).all()
        
        result = []
        for conv in conversations:
            agent_data = None
            if conv.created_agent_id:
                agent = db.query(Agent).filter(Agent.id == conv.created_agent_id).first()
                if agent:
                    agent_data = {
                        "id": str(agent.id),
                        "agent_name": agent.agent_name,
                        "business_type": agent.business_type,
                        "status": agent.status,
                        "avatar_url": agent.avatar_url,
                        "persona": agent.persona
                    }
            
            result.append({
                "id": str(conv.id),
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "agent": agent_data
            })
        
        logger.info(f"📋 Найдено {len(result)} conversations для user_id={user_id}")
        return result
    
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{conversation_id}", response_model=ConstructorHistoryResponse)
async def get_constructor_history(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """Получить историю конкретного диалога с конструктором"""
    try:
        # Ищем conversation по ID
        conversation = db.query(ConstructorConversation).filter(
            ConstructorConversation.id == conversation_id
        ).first()
        
        if conversation:
            messages = [Message(**msg) for msg in conversation.messages]
            logger.info(f"📖 Загружена история conversation_id={conversation_id}, сообщений: {len(messages)}")
            return ConstructorHistoryResponse(messages=messages)
        
        # Если истории нет, возвращаем пустой массив
        logger.warning(f"⚠️ Conversation {conversation_id} не найдена")
        return ConstructorHistoryResponse(messages=[])
    
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке истории: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
                plan="free"
            )
            db.add(new_user)
            db.commit()
            logger.info(f"✅ Пользователь создан: {user_id}")

        # Загружаем или создаём сессию конструктора
        conversation_record = None
        
        # Если передан conversation_id → загружаем эту conversation
        if request.conversation_id:
            logger.info(f"📂 Загрузка conversation: {request.conversation_id}")
            conversation_record = db.query(ConstructorConversation).filter(
                ConstructorConversation.id == request.conversation_id,
                ConstructorConversation.user_id == user_id
            ).first()
            
            if not conversation_record:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Conversation {request.conversation_id} not found"
                )
        
        # Если НЕТ conversation_id → создаём НОВУЮ
        else:
            logger.info(f"🆕 Создание новой conversation")
            conversation_record = ConstructorConversation(
                id=uuid4(),
                user_id=user_id,
                messages=[],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(conversation_record)
            db.flush()  # Получаем ID сразу
        
        # Преобразуем request.messages в список словарей
        conversation = [msg.dict() for msg in request.messages]
        
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
        
        # Добавляем ответ в историю
        conversation.append({
            "role": "assistant",
            "content": assistant_response
        })
        
        # ✅ НОВАЯ ЛОГИКА: Создаём draft-агента после первого сообщения пользователя
        if not conversation_record.created_agent_id:
            # Проверяем, что это НЕ первое системное сообщение
            user_messages_count = sum(1 for msg in conversation if msg.get('role') == 'user')
            
            if user_messages_count >= 1:  # Есть хотя бы одно сообщение от пользователя
                logger.info("📝 Создаём draft-агента (диалог начат)")
                
                draft_agent = Agent(
                    id=uuid4(),
                    user_id=user_id,
                    agent_name="Агент (в разработке)",  # Временное имя
                    business_type="Не указано",  # Временный тип
                    persona="victoria",  # Дефолтная персона
                    system_prompt=None,  # Пока нет промпта
                    knowledge_base={},  # Пустая база знаний
                    status="draft",  # ✅ Статус draft
                    constructor_conversation_id=conversation_record.id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(draft_agent)
                db.flush()
                
                # Сохраняем связь
                conversation_record.created_agent_id = draft_agent.id
                
                logger.info(f"✅ Draft-агент создан: {draft_agent.id}")
        
        # Сохраняем историю в БД
        conversation_record.messages = conversation
        conversation_record.updated_at = datetime.utcnow()
        db.commit()
        
        # Проверяем готовность агента (CREATE)
        agent_data = parse_agent_ready_response(assistant_response)
        
        if agent_data:
            logger.info(f"✅ Создаём/обновляем агента (AGENT-READY)...")
            
            agent_name = agent_data["agent_name"]
            business_type = agent_data["business_type"]
            kb_dict = agent_data["knowledge_base"]
            
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=kb_dict
            )
            
            persona_name = "victoria" if "виктория" in agent_name.lower() else "alexander"
            
            # ✅ Ищем существующего draft-агента через conversation
            existing_agent = None
            if conversation_record.created_agent_id:
                existing_agent = db.query(Agent).filter(
                    Agent.id == conversation_record.created_agent_id
                ).first()
            
            if existing_agent:
                # ✅ Обновляем draft → test
                existing_agent.agent_name = agent_name
                existing_agent.business_type = business_type
                existing_agent.persona = persona_name
                existing_agent.system_prompt = system_prompt
                existing_agent.knowledge_base = kb_dict
                existing_agent.status = "test"  # ✅ Активируем в режим тестирования
                existing_agent.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"✅ Агент активирован (draft → test)! ID: {existing_agent.id}")
                
                return ConstructorChatResponse(
                    status="agent_ready",
                    agent_id=str(existing_agent.id),
                    conversation_id=str(conversation_record.id),
                    agent_data=AgentData(
                        agent_name=agent_name,
                        business_type=business_type,
                        description=business_type,
                        instructions=system_prompt,
                        knowledge_base=kb_dict
                    )
                )
            else:
                # ⚠️ Не должно происходить (draft должен был создаться раньше)
                logger.warning("⚠️ Draft-агент не найден, создаём новый сразу в статусе test")
                new_agent = Agent(
                    id=uuid4(),
                    user_id=user_id,
                    agent_name=agent_name,
                    business_type=business_type,
                    persona=persona_name,
                    system_prompt=system_prompt,
                    knowledge_base=kb_dict,
                    status="test",  # ✅ Сразу в test
                    constructor_conversation_id=conversation_record.id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_agent)
                db.flush()
                
                # Сохраняем связь
                conversation_record.created_agent_id = new_agent.id
                
                db.commit()
                db.refresh(new_agent)
                
                logger.info(f"✅ Агент создан! ID: {new_agent.id}")
                
                return ConstructorChatResponse(
                    status="agent_ready",
                    agent_id=str(new_agent.id),
                    conversation_id=str(conversation_record.id),
                    agent_data=AgentData(
                        agent_name=agent_name,
                        business_type=business_type,
                        description=business_type,
                        instructions=system_prompt,
                        knowledge_base=kb_dict
                    )
                )
        
        # Проверяем обновление агента (UPDATE)
        update_data_response = parse_agent_update_response(assistant_response)
        
        if update_data_response:
            logger.info(f"✅ Обновление агента (AGENT-UPDATE)...")
            
            update_data = update_data_response["update_data"]
            
            # ✅ Ищем агента через conversation
            if not conversation_record.created_agent_id:
                logger.error("❌ Агент ещё не создан!")
                return ConstructorChatResponse(
                    response="Ошибка: агент ещё не создан. Сначала завершите создание агента."
                )
            
            existing_agent = db.query(Agent).filter(
                Agent.id == conversation_record.created_agent_id
            ).first()
            
            if not existing_agent:
                logger.error("❌ Агент не найден для обновления!")
                return ConstructorChatResponse(
                    response="Ошибка: агент не найден."
                )
            
            # МЕРЖ логика: обновляем только переданные поля
            current_kb = existing_agent.knowledge_base or {}
            
            # Обновляем каждое поле из update_data
            for key, value in update_data.items():
                current_kb[key] = value
            
            # Пересоздаём system_prompt с обновлёнными данными
            system_prompt = generate_seller_prompt(
                agent_name=existing_agent.agent_name,
                business_type=existing_agent.business_type,
                knowledge_base=current_kb
            )
            
            # Обновляем агента в БД
            existing_agent.knowledge_base = current_kb
            existing_agent.system_prompt = system_prompt
            existing_agent.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"✅ Агент обновлён (мерж)! ID: {existing_agent.id}")
            logger.info(f"   Обновлённые поля: {list(update_data.keys())}")
            
            return ConstructorChatResponse(
                status="agent_updated",
                agent_id=str(existing_agent.id),
                conversation_id=str(conversation_record.id),
                agent_data=AgentData(
                    agent_name=existing_agent.agent_name,
                    business_type=existing_agent.business_type,
                    description=existing_agent.business_type,
                    instructions=system_prompt,
                    knowledge_base=current_kb
                )
            )
        
        return ConstructorChatResponse(
            response=assistant_response,
            conversation_id=str(conversation_record.id)
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в constructor_chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
