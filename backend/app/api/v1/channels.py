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
    For Telegram: verifies bot token and sets webhook automatically.
    """
    import os

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

    # Verify bot token first
    bot_info = None
    if request.channel_type == "telegram":
        bot_token = request.credentials.get("bot_token")
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token is required for Telegram")
        bot_info = await verify_telegram_bot(bot_token)

    elif request.channel_type == "max":
        bot_token = request.credentials.get("bot_token")
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token is required for Max")
        bot_info = await verify_max_bot(bot_token)

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

    # Generate webhook URL using Railway URL
    base_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "neuro-seller-production.up.railway.app")
    webhook_url = f"https://{base_url}/api/v1/channels/webhook/{request.channel_type}/{channel.id}"

    channel.webhook_url = webhook_url
    db.commit()

    # Set webhook based on channel type
    if request.channel_type == "telegram":
        bot_token = request.credentials.get("bot_token")
        await set_telegram_webhook(bot_token, webhook_url)
        channel.webhook_verified = True
        channel.settings = {"bot_username": bot_info.get("username"), "bot_name": bot_info.get("first_name")}
        db.commit()

    elif request.channel_type == "max":
        bot_token = request.credentials.get("bot_token")
        await set_max_webhook(bot_token, webhook_url)
        channel.webhook_verified = True
        channel.settings = {"bot_name": bot_info.get("name"), "bot_username": bot_info.get("username")}
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


@router.delete("/{channel_id}")
async def disconnect_channel(
    channel_id: str,
    db: Session = Depends(get_db)
):
    """
    Disconnect and delete a channel.
    For Telegram: removes webhook from Telegram API.
    """
    # Get channel
    channel = db.query(AgentChannel).filter(AgentChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Remove webhook based on channel type
    bot_token = channel.credentials.get("bot_token")
    if bot_token:
        if channel.channel_type == "telegram":
            await delete_telegram_webhook(bot_token)
        elif channel.channel_type == "max":
            await delete_max_webhook(bot_token)

    # Delete channel from database
    db.delete(channel)
    db.commit()

    return {"status": "disconnected", "channel_id": channel_id}


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
        response_text = await chat_completion(messages=messages, temperature=0.8)

        # Save assistant message
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            text=response_text,
            tokens_used=0
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


@router.post("/webhook/max/{channel_id}")
async def max_webhook(
    channel_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Webhook endpoint for Max messenger updates.
    """
    # Get channel
    channel = db.query(AgentChannel).filter(AgentChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Get agent
    agent = db.query(Agent).filter(Agent.id == channel.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Parse Max update
    update = await request.json()

    # Max sends update_type to indicate event type
    update_type = update.get("update_type")

    # Handle message_created event
    if update_type != "message_created":
        return {"ok": True}

    # Extract message data
    message = update.get("message", {})
    sender = message.get("sender", {})
    user_id = str(sender.get("user_id", ""))
    username = sender.get("username", "")
    text = message.get("body", {}).get("text", "")
    chat_id = str(update.get("chat_id", ""))

    if not text or not chat_id:
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
        response_text = await chat_completion(messages=messages, temperature=0.8)

        # Save assistant message
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            text=response_text,
            tokens_used=0
        )
        db.add(assistant_message)

        # Update conversation
        conversation.last_message_at = datetime.utcnow()
        channel.messages_count += 1
        channel.last_message_at = datetime.utcnow()

        db.commit()

        # Send response back to Max
        await send_max_message(
            bot_token=channel.credentials.get("bot_token"),
            chat_id=chat_id,
            text=response_text
        )

        return {"ok": True}

    except Exception as e:
        db.rollback()
        print(f"❌ Error processing Max message: {e}")
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


async def verify_telegram_bot(bot_token: str) -> dict:
    """
    Verify bot token via getMe API.
    Returns bot info if valid, raises exception if invalid.
    """
    import httpx

    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

        if not data.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bot token: {data.get('description', 'Unknown error')}"
            )

        return data.get("result")


async def set_telegram_webhook(bot_token: str, webhook_url: str) -> bool:
    """
    Set webhook for Telegram bot.
    """
    import httpx

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "url": webhook_url,
            "allowed_updates": ["message"]
        })
        data = response.json()

        if not data.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to set webhook: {data.get('description', 'Unknown error')}"
            )

        return True


async def delete_telegram_webhook(bot_token: str) -> bool:
    """
    Delete webhook for Telegram bot.
    """
    import httpx

    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"

    async with httpx.AsyncClient() as client:
        response = await client.post(url)
        data = response.json()

        return data.get("ok", False)


# ============== MAX Bot API Functions ==============

MAX_API_URL = "https://platform-api.max.ru"


async def verify_max_bot(bot_token: str) -> dict:
    """
    Verify Max bot token via /me API.
    Returns bot info if valid, raises exception if invalid.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{MAX_API_URL}/me",
            headers={"Authorization": bot_token}
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid Max bot token: {response.text}"
            )

        return response.json()


async def set_max_webhook(bot_token: str, webhook_url: str) -> bool:
    """
    Set webhook subscription for Max bot.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MAX_API_URL}/subscriptions",
            headers={
                "Authorization": bot_token,
                "Content-Type": "application/json"
            },
            json={"url": webhook_url}
        )

        if response.status_code not in [200, 201]:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to set Max webhook: {response.text}"
            )

        return True


async def delete_max_webhook(bot_token: str) -> bool:
    """
    Delete webhook subscription for Max bot.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{MAX_API_URL}/subscriptions",
            headers={"Authorization": bot_token}
        )

        return response.status_code in [200, 204]


async def send_max_message(bot_token: str, chat_id: str, text: str):
    """
    Send message via Max Bot API.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MAX_API_URL}/messages",
            headers={
                "Authorization": bot_token,
                "Content-Type": "application/json"
            },
            json={
                "chat_id": int(chat_id),
                "text": text
            }
        )

        return response.json()
