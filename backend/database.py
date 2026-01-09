"""База данных"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Text, DateTime, Integer, JSON
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(String, primary_key=True)
    user_id = Column(String)
    agent_name = Column(String)
    business_type = Column(Text)
    knowledge_base = Column(Text)
    system_prompt = Column(Text)
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String)
    channel = Column(String)
    messages = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class Database:
    """Управление базой данных"""
    
    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=True)
        self.async_session = async_sessionmaker(
            self.engine, 
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def init_db(self):
        """Создание таблиц"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def create_agent(
        self,
        user_id: str,
        agent_name: str,
        business_type: str,
        knowledge_base: str,
        system_prompt: str
    ) -> str:
        """Создание агента"""
        import uuid
        agent_id = str(uuid.uuid4())
        
        async with self.async_session() as session:
            agent = Agent(
                id=agent_id,
                user_id=user_id,
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=knowledge_base,
                system_prompt=system_prompt,
                status="draft"
            )
            session.add(agent)
            await session.commit()
        
        return agent_id
    
    async def get_agent(self, agent_id: str):
        """Получить агента"""
        async with self.async_session() as session:
            result = await session.get(Agent, agent_id)
            if result:
                return {
                    "id": result.id,
                    "agent_name": result.agent_name,
                    "business_type": result.business_type,
                    "knowledge_base": result.knowledge_base,
                    "system_prompt": result.system_prompt,
                    "status": result.status
                }
            return None
    
    async def update_agent_status(self, agent_id: str, status: str):
        """Обновить статус агента"""
        async with self.async_session() as session:
            agent = await session.get(Agent, agent_id)
            if agent:
                agent.status = status
                await session.commit()
    
    async def get_user_agents(self, user_id: str):
        """Получить всех агентов пользователя"""
        from sqlalchemy import select
        
        async with self.async_session() as session:
            result = await session.execute(
                select(Agent).where(Agent.user_id == user_id)
            )
            agents = result.scalars().all()
            return [
                {
                    "id": agent.id,
                    "agent_name": agent.agent_name,
                    "business_type": agent.business_type,
                    "status": agent.status,
                    "created_at": agent.created_at.isoformat()
                }
                for agent in agents
            ]
    
    async def save_conversation(self, agent_id: str, channel: str, messages: list):
        """Сохранить диалог"""
        async with self.async_session() as session:
            conversation = Conversation(
                agent_id=agent_id,
                channel=channel,
                messages=messages
            )
            session.add(conversation)
            await session.commit()
