from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=True)
    telegram_id = Column(String, unique=True, nullable=True, index=True)
    plan = Column(String, default="free")
    tokens_limit = Column(Integer, default=60)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship с Agent
    agents = relationship("Agent", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, telegram_id={self.telegram_id}, plan={self.plan})>"
