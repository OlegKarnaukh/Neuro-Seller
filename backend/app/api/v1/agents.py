"""
Agents API - CRUD operations for seller agents
"""
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
