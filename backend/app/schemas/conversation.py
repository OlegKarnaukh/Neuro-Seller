"""
Pydantic schemas for conversations
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    text: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: Optional[str] = None
    client_name: Optional[str] = None
    channel: Optional[str] = None
    status: str
    started_at: datetime
    last_message_at: datetime
    messages_count: int = 0
    last_message: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: Optional[str] = None
    client_name: Optional[str] = None
    channel: Optional[str] = None
    status: str
    started_at: datetime
    last_message_at: datetime
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True
