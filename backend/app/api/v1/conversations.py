"""
Conversations endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func
from typing import List, Optional
import uuid

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.agent import Agent
from app.models.channel import AgentChannel
from app.schemas.conversation import ConversationResponse, ConversationDetail

router = APIRouter()


@router.get("/", response_model=List[ConversationResponse])
async def list_conversations(
    agent_id: Optional[uuid.UUID] = Query(None, description="Filter by agent ID"),
    channel: Optional[str] = Query(None, description="Filter by channel (telegram, whatsapp, etc)"),
    status: Optional[str] = Query(None, description="Filter by status (active, completed)"),
    limit: int = Query(50, le=100, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of all conversations for current user"""
    # Build query
    query = (
        select(Conversation, Agent, AgentChannel, func.count(Message.id).label("messages_count"))
        .join(Agent, Conversation.agent_id == Agent.id)
        .outerjoin(AgentChannel, Conversation.channel_id == AgentChannel.id)
        .outerjoin(Message, Conversation.id == Message.conversation_id)
        .where(Agent.user_id == current_user.id)
        .group_by(Conversation.id, Agent.id, AgentChannel.id)
    )

    # Apply filters
    if agent_id:
        query = query.where(Conversation.agent_id == agent_id)
    if channel:
        query = query.where(AgentChannel.channel_type == channel)
    if status:
        query = query.where(Conversation.status == status)

    # Order by last message
    query = query.order_by(Conversation.last_message_at.desc())
    query = query.offset(offset).limit(limit)

    # Execute query
    results = db.execute(query).all()

    # Transform results
    conversations = []
    for conv, agent, channel_obj, msg_count in results:
        # Get last message
        last_msg = db.execute(
            select(Message.text)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        conversations.append(ConversationResponse(
            id=conv.id,
            agent_id=conv.agent_id,
            agent_name=agent.name if agent else None,
            client_name=conv.external_username or f"User {conv.external_user_id[:8]}",
            channel=channel_obj.channel_type if channel_obj else None,
            status=conv.status,
            started_at=conv.started_at,
            last_message_at=conv.last_message_at,
            messages_count=msg_count,
            last_message=last_msg
        ))

    return conversations


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed conversation with full message history"""
    # Get conversation with messages
    conversation = db.execute(
        select(Conversation)
        .options(joinedload(Conversation.messages), joinedload(Conversation.agent))
        .where(Conversation.id == conversation_id)
    ).scalar_one_or_none()

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    # Check if user owns this conversation's agent
    if conversation.agent.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Get channel info
    channel_name = None
    if conversation.channel_id:
        channel = db.execute(
            select(AgentChannel).where(AgentChannel.id == conversation.channel_id)
        ).scalar_one_or_none()
        if channel:
            channel_name = channel.channel_type

    return ConversationDetail(
        id=conversation.id,
        agent_id=conversation.agent_id,
        agent_name=conversation.agent.name,
        client_name=conversation.external_username or f"User {conversation.external_user_id[:8]}",
        channel=channel_name,
        status=conversation.status,
        started_at=conversation.started_at,
        last_message_at=conversation.last_message_at,
        messages=[
            {"id": msg.id, "role": msg.role, "text": msg.text, "created_at": msg.created_at}
            for msg in sorted(conversation.messages, key=lambda m: m.created_at)
        ]
    )
