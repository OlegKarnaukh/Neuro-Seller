"""
Channels API - Connect agents to communication channels
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime

from app.core.database import get_db
from app.models.agent import Agent
from app.models.channel import AgentChannel
from app.models.conversation import Conversation, Message
from app.services.openai_service import chat_completion

router = APIRouter()


class ConnectChannelRequest(BaseModel):
    agent_id: str
    channel_type: str  # telegram, whatsapp, vk, avito
    credentials: Dict  # {"bot_token": "..."} для Telegram


class ConnectChannelResponse(BaseModel):
    id: str
    webhook_url: str
    status: str


class ChannelResponse(BaseModel):
    id: str
    agent_id: str
    channel_type: str
    is_active: bool
    webhook_verified: bool
    messages_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.post("/connect", response_model=ConnectChannelResponse)
async def connect_channel(
    request: ConnectChannelRequest,
    db: Session = Depends(get_db)
):
    """
    Connect an agent to a communication channel.
    """
    # Verify agent exists
    agent = db.query(Agent).filter(Agent.id == request.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Check if channel already exists
    existing = db.query(AgentChannel).filter(
        AgentChannel.agent_id == request.agent_id,
        AgentChannel.channel_type == request.channel_type
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Channel already connected")
    
    # Create channel
    channel = AgentChannel(
        agent_id=request.agent_id,
        channel_type=request.channel_type,
        credentials=request.credentials,
        is_active=True
    )
    
    db.add(channel)
    db.commit()
    db.refresh(channel)
    
    # Generate webhook URL
    from app.core.config import settings
    webhook_url = f"https://api.neuro-seller.com/api/v1/channels/webhook/{request.channel_type}/{channel.id}"
    
    channel.webhook_url = webhook_url
    db.commit()
    
    return ConnectChannelResponse(
        id=str(channel.id),
        webhook_url=webhook_url,
        status="connected"
    )


@router.get("/agent/{agent_id}", response_model=list[ChannelResponse])
async def get_agent_channels(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """
    Get all channels for an agent.
    """
    channels = db.query(AgentChannel).filter(
        AgentChannel.agent_id == agent_id
    ).all()
    
    return channels


@router.post("/webhook/telegram/{channel_id}")
async def telegram_webhook(
    channel_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Webhook endpoint for Telegram updates.
    """
    # Get channel
    channel = db.query(AgentChannel).filter(AgentChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Get agent
    agent = db.query(Agent).filter(Agent.id == channel.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Parse Telegram update
    update = await request.json()
    
    # Extract message data
    if "message" not in update:
        return {"ok": True}
    
    message = update["message"]
    user_id = str(message["from"]["id"])
    username = message["from"].get("username", "")
    text = message.get("text", "")
    
    if not text:
        return {"ok": True}
    
    # Get or create conversation
    conversation = db.query(Conversation).filter(
        Conversation.agent_id == agent.id,
        Conversation.channel_id == channel.id,
        Conversation.external_user_id == user_id,
        Conversation.status == "active"
    ).first()
    
    if not conversation:
        conversation = Conversation(
            agent_id=agent.id,
            channel_id=channel.id,
            external_user_id=user_id,
            external_username=username,
            status="active"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    
    # Save user message
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        text=text
    )
    db.add(user_message)
    
    # Get conversation history
    history_messages = db.query(Message).filter(
        Message.conversation_id == conversation.id
    ).order_by(Message.created_at).limit(20).all()
    
    # Prepare messages for OpenAI
    messages = [{"role": "system", "content": agent.system_prompt}]
    
    for msg in history_messages:
        messages.append({
            "role": msg.role,
            "content": msg.text
        })
    
    messages.append({"role": "user", "content": text})
    
    # Call OpenAI
    try:
        result = await chat_completion(messages=messages, temperature=0.8)
        response_text = result["content"]
        
        # Save assistant message
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            text=response_text,
            tokens_used=result["tokens_used"]
        )
        db.add(assistant_message)
        
        # Update conversation
        conversation.last_message_at = datetime.utcnow()
        channel.messages_count += 1
        channel.last_message_at = datetime.utcnow()
        
        db.commit()
        
        # Send response back to Telegram
        await send_telegram_message(
            bot_token=channel.credentials.get("bot_token"),
            chat_id=user_id,
            text=response_text
        )
        
        return {"ok": True}
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error processing message: {e}")
        return {"ok": False, "error": str(e)}


async def send_telegram_message(bot_token: str, chat_id: str, text: str):
    """
    Send message via Telegram Bot API.
    """
    import httpx
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        })
        
        return response.json()
