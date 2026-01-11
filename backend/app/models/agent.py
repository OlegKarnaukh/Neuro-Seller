from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base

class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    agent_name = Column(String(255), nullable=False)
    business_type = Column(String(255), nullable=False)
    persona = Column(String(50), default="victoria")
    
    knowledge_base = Column(JSONB, default=dict)
    system_prompt = Column(Text, nullable=True)
    
    avatar_url = Column(Text, nullable=True)
    
    # Связь с conversation, из которой создан агент
    constructor_conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="agents")
    channels = relationship("AgentChannel", back_populates="agent", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="agent", cascade="all, delete-orphan")
