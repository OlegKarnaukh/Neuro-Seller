"""
Agents API - CRUD operations for seller agents
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.services.openai_service import chat_completion

router = APIRouter()
logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    id: str
    user_id: str
    agent_name: str
    business_type: str
    persona: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


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
        
        # Отправляем запрос к OpenAI
        response = chat_completion(
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
        result = await chat_completion(messages=messages, temperature=0.8)
        
        return TestAgentResponse(
            response=result["content"],
            tokens_used=result["tokens_used"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")
