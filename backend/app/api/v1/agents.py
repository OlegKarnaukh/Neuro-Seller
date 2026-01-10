"""
Agents API - CRUD operations for seller agents
"""
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_serializer
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.services.openai_service import chat_completion

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
    tokens_used: int


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    agent_name: str
    response: str


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


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    request: UpdateAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Update an agent's information.
    
    Allows updating:
    - agent_name: Display name of the agent
    - business_type: Type of business (e.g., "Салон красоты")
    - system_prompt: Full system prompt with instructions
    - knowledge_base: JSON object with business data
    - avatar_url: URL to agent's avatar image
    - status: Agent status (draft/active/archived)
    """
    try:
        # Получаем агента из БД
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        # Обновляем только переданные поля
        update_data = request.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            setattr(agent, field, value)
        
        # Обновляем timestamp
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
    
    return {"message": "Agent deleted successfully"}


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    agent_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Chat with an agent-seller.
    
    The agent uses its system_prompt (containing business knowledge and persona)
    to respond to customer messages.
    """
    try:
        # Получаем агента из БД
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
        
        # Формируем контекст для OpenAI
        messages = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": request.message}
        ]
        
        logger.info(f"💬 Отправка сообщения агенту {agent.agent_name} (ID: {agent_id})")
        logger.info(f"📝 Сообщение пользователя: {request.message}")
        
        # Отправляем запрос к OpenAI (ASYNC)
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
        # Пробрасываем HTTP ошибки дальше
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка в chat_with_agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test", response_model=TestAgentResponse)
async def test_agent(
    request: TestAgentRequest,
    db: Session = Depends(get_db)
):
    """
    Test an agent with a message (for Preview in Base44).
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
        
        # chat_completion теперь возвращает просто строку, а не dict
        return TestAgentResponse(
            response=response,
            tokens_used=0  # Токены можно добавить позже, если нужно
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")
