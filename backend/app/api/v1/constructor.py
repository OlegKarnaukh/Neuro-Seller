"""
Constructor API - Meta-Agent for creating seller agents
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.core.database import get_db
from app.services.openai_service import chat_completion, parse_agent_ready_response
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt
from app.models.user import User
from app.models.agent import Agent

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[ChatMessage]


class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool = False
    agent_id: Optional[str] = None


# In-memory conversation storage (будет заменено на БД позже)
conversations = {}


@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Chat with Meta-Agent to create a new seller agent.
    """
    user_id = request.user_id
    
    # Initialize conversation history
    if user_id not in conversations:
        conversations[user_id] = {
            "history": [
                {"role": "system", "content": META_AGENT_PROMPT}
            ]
        }
    
    # Add user message to history
    conversations[user_id]["history"].append({
        "role": "user",
        "content": request.messages[-1].content
    })
    
    # Call OpenAI
    try:
        result = await chat_completion(
            messages=conversations[user_id]["history"],
            temperature=0.8
        )
        
        response_text = result["content"]
        
        # Add assistant response to history
        conversations[user_id]["history"].append({
            "role": "assistant",
            "content": response_text
        })
        
        # Check if agent is ready
        agent_data = await parse_agent_ready_response(response_text)
        
        if agent_data:
            # Create agent in database
            
            # Get or create user
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                # Create demo user
                user = User(id=user_id, email=f"{user_id}@temp.com")
                db.add(user)
                db.commit()
            
            # Generate system prompt for seller
            system_prompt = generate_seller_prompt(
                agent_name=agent_data["agent_name"],
                business_type=agent_data["business_type"],
                knowledge_base=agent_data["knowledge_base"]
            )
            
            # Create agent
            agent = Agent(
                user_id=user.id,
                agent_name=agent_data["agent_name"],
                business_type=agent_data["business_type"],
                persona=agent_data["agent_name"].lower(),
                knowledge_base=agent_data["knowledge_base"],
                system_prompt=system_prompt,
                status="active"
            )
            
            db.add(agent)
            db.commit()
            db.refresh(agent)
            
            # Clear conversation
            del conversations[user_id]
            
            return ConstructorChatResponse(
                response=response_text,
                agent_created=True,
                agent_id=str(agent.id)
            )
        
        return ConstructorChatResponse(
            response=response_text,
            agent_created=False
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")
