from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base

class AgentChannel(Base):
    __tablename__ = "agent_channels"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    
    channel_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    
    credentials = Column(JSONB, default=dict)
    webhook_url = Column(String(500), nullable=True)
    webhook_verified = Column(Boolean, default=False)
    
    settings = Column(JSONB, default=dict)
    messages_count = Column(Integer, default=0)
    last_message_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = relationship("Agent", back_populates="channels")
