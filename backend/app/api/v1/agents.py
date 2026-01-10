"""
Agents API - CRUD operations for seller agents
"""
import logging
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_serializer
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.services.openai_service import chat_completion
from app.prompts import generate_seller_prompt

router = APIRouter()
logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    id: UUID
    user_id: UUID
    agent_name: str
    business_type: str
    persona: str
    avatar_url: Optional[str] = None
    knowledge_base: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    
    # Автоматически конвертируем UUID в строку при сериализации
    @field_serializer('id', 'user_id')
    def serialize_uuid(self, value: UUID, _info) -> str:
        return str(value)
    
    class Config:
        from_attributes = True


class CreateAgentRequest(BaseModel):
    user_id: str
    agent_name: str
    business_type: str
    knowledge_base: Optional[Dict[str, Any]] = None
    avatar_url: Optional[str] = None
    persona: Optional[str] = None
    status: Optional[str] = "draft"


class UpdateAgentRequest(BaseModel):
    agent_name: Optional[str] = None
    business_type: Optional[str] = None
    system_prompt: Optional[str] = None
    knowledge_base: Optional[Dict[str, Any]] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = None


class TestAgentRequest(BaseModel):
    agent_id: str
    message: str


class TestAgentResponse(BaseModel):
    response: str
    agent_name: str  # ✅ Добавлено для Base44


class SaveAgentRequest(BaseModel):
    agent_id: str


class SaveAgentResponse(BaseModel):
    success: bool
    redirect_url: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    agent_name: str
    response: str


# Дефолтные аватарки по персонам
DEFAULT_AVATARS = {
    "victoria": "https://cdn.example.com/avatars/female-default.png",
    "alexander": "https://cdn.example.com/avatars/male-default.png",
}


# ============================================================
# ВАЖНО: Специфичные роуты ПЕРЕД общими!
# ============================================================

@router.post("/test", response_model=TestAgentResponse)
async def test_agent(
    request: TestAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Test an agent with a message (for Preview in Base44).
    
    Base44 Integration:
    - Request: {"agent_id": "...", "message": "..."}
    - Response: {"response": "...", "agent_name": "Виктория"}
    """
    agent = db.query(Agent).filter(Agent.id == request.agent_id).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if not agent.system_prompt:
        raise HTTPException(status_code=400, detail="Agent not configured")
    
    # Prepare messages
    messages = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": request.message}
    ]
    
    try:
        # ASYNC call
        response = await chat_completion(messages=messages, temperature=0.8)
        
        # ✅ Возвращаем response + agent_name для Base44
        return TestAgentResponse(
            response=response,
            agent_name=agent.agent_name
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")


@router.post("/save", response_model=SaveAgentResponse)
async def save_agent(
    request: SaveAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Save agent (activate it) - for Base44 integration.
    
    Base44 Integration:
    - Request: {"agent_id": "..."}
    - Response: {"success": true, "redirect_url": "/dashboard"}
    
    Changes agent status from 'draft' to 'active'.
    """
    try:
        agent = db.query(Agent).filter(Agent.id == request.agent_id).first()
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        # Активируем агента
        agent.status = "active"
        agent.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(agent)
        
        logger.info(f"✅ Агент {agent.agent_name} (ID: {request.agent_id}) активирован")
        
        return SaveAgentResponse(
            success=True,
            redirect_url="/dashboard"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка активации агента {request.agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save agent: {str(e)}")


@router.get("/detail/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """
    Get specific agent by ID.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return agent


async def _create_agent_logic(
    request: CreateAgentRequest,
    db: Session
) -> Agent:
    """
    Общая логика создания агента (используется для обоих вариантов роута).
    """
    # Проверяем, что пользователь существует
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Определяем персону
    persona = request.persona
    if not persona:
        # Автоопределение по имени агента
        agent_name_lower = request.agent_name.lower()
        if any(name in agent_name_lower for name in ["виктория", "victoria", "анна", "мария", "елена"]):
            persona = "victoria"
        else:
            persona = "alexander"
    
    # Устанавливаем дефолтную аватарку, если не указана
    avatar_url = request.avatar_url or DEFAULT_AVATARS.get(persona)
    
    # Генерируем system_prompt из базы знаний
    knowledge_base = request.knowledge_base or {}
    system_prompt = generate_seller_prompt(
        agent_name=request.agent_name,
        business_type=request.business_type,
        knowledge_base=knowledge_base
    )
    
    # Создаём агента
    new_agent = Agent(
        id=uuid4(),
        user_id=request.user_id,
        agent_name=request.agent_name,
        business_type=request.business_type,
        persona=persona,
        knowledge_base=knowledge_base,
        system_prompt=system_prompt,
        avatar_url=avatar_url,
        status=request.status or "draft",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    
    logger.info(f"✅ Агент '{new_agent.agent_name}' создан вручную (ID: {new_agent.id})")
    logger.info(f"   user_id: {request.user_id}")
    logger.info(f"   business_type: {request.business_type}")
    logger.info(f"   persona: {persona}")
    logger.info(f"   status: {request.status or 'draft'}")
    
    return new_agent


@router.post("/create", response_model=AgentResponse)
@router.post("/create/", response_model=AgentResponse)
async def create_agent(
    request: CreateAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Создать агента вручную (без мета-агента).
    """
    try:
        return await _create_agent_logic(request, db)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания агента: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    request: UpdateAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Update an agent's information.
    """
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        update_data = request.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            setattr(agent, field, value)
        
        agent.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(agent)
        
        logger.info(f"✅ Агент {agent.agent_name} (ID: {agent_id}) обновлён")
        logger.info(f"   Обновлённые поля: {list(update_data.keys())}")
        
        return agent
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления агента {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete an agent.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    db.delete(agent)
    db.commit()
    
    logger.info(f"🗑️ Агент {agent.agent_name} (ID: {agent_id}) удалён")
    
    return {"message": "Agent deleted successfully"}


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    agent_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Chat with an agent-seller.
    """
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        if agent.status != "active":
            raise HTTPException(
                status_code=400, 
                detail=f"Agent is not active (status: {agent.status})"
            )
        
        if not agent.system_prompt:
            raise HTTPException(
                status_code=400, 
                detail="Agent has no system prompt configured"
            )
        
        messages = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": request.message}
        ]
        
        logger.info(f"💬 Отправка сообщения агенту {agent.agent_name} (ID: {agent_id})")
        logger.info(f"📝 Сообщение пользователя: {request.message}")
        
        response = await chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.7
        )
        
        logger.info(f"✅ Получен ответ от агента: {response[:100]}...")
        
        return ChatResponse(
            agent_id=agent_id,
            agent_name=agent.agent_name,
            response=response
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка в chat_with_agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}", response_model=List[AgentResponse])
async def get_user_agents(
    user_id: str,
    db: Session = Depends(get_db)
):
    """
    Get all agents for a specific user.
    """
    agents = db.query(Agent).filter(Agent.user_id == user_id).all()
    return agents
