import re
from typing import Dict, List
from datetime import datetime
from ai_client import AIClient
from database import Database
from prompts import META_AGENT_PROMPT, generate_seller_prompt

class AgentManager:
    """Управление созданием и работой агентов"""
    
    def __init__(self, db: Database):
        self.ai = AIClient()
        self.db = db
        self.sessions = {}
    
    async def handle_constructor_message(
        self,
        user_id: str,
        message: str,
        files: List[str] = []
    ) -> Dict:
        """Обработка сообщения в конструкторе"""
        
        if user_id not in self.sessions:
            self.sessions[user_id] = {
                "messages": [],
                "collected_data": {}
            }
        
        session = self.sessions[user_id]
        
        if files:
            file_content = await self._process_files(files)
            message += f"\n\n[Прикреплённые файлы]:\n{file_content}"
        
        session["messages"].append({"role": "user", "content": message})
        
        ai_messages = [
            {"role": "system", "content": META_AGENT_PROMPT},
            *session["messages"]
        ]
        
        response = await self.ai.chat(ai_messages, temperature=0.7)
        session["messages"].append({"role": "assistant", "content": response})
        
        if "[AGENT_READY]" in response:
            agent_id = await self._create_agent(user_id, response)
            clean_response = self._clean_tags(response)
            del self.sessions[user_id]
            
            return {
                "response": clean_response,
                "agent_created": True,
                "agent_id": agent_id
            }
        
        return {
            "response": response,
            "agent_created": False
        }
    
    async def _create_agent(self, user_id: str, final_message: str) -> str:
        """Создание агента из финального сообщения"""
        
        agent_name = re.search(r'\[AGENT_NAME: ([^\]]+)\]', final_message)
        business_type = re.search(r'\[BUSINESS_TYPE: ([^\]]+)\]', final_message)
        knowledge_base = re.search(r'\[KNOWLEDGE_BASE: ([^\]]+)\]', final_message)
        
        if not all([agent_name, business_type, knowledge_base]):
            raise ValueError("Missing required agent data")
        
        agent_name = agent_name.group(1)
        business_type = business_type.group(1)
        knowledge_base = knowledge_base.group(1)
        
        system_prompt = generate_seller_prompt(
            agent_name=agent_name,
            business_type=business_type,
            knowledge_base=knowledge_base
        )
        
        agent_id = await self.db.create_agent(
            user_id=user_id,
            agent_name=agent_name,
            business_type=business_type,
            knowledge_base=knowledge_base,
            system_prompt=system_prompt
        )
        
        return agent_id
    
    async def test_agent(self, agent_id: str, message: str) -> Dict:
        """Тестирование агента"""
        
        agent = await self.db.get_agent(agent_id)
        
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        
        response = await self.ai.chat(
            messages=[
                {"role": "system", "content": agent["system_prompt"]},
                {"role": "user", "content": message}
            ],
            temperature=0.8
        )
        
        await self.db.save_conversation(
            agent_id=agent_id,
            channel="test",
            messages=[
                {"role": "user", "content": message},
                {"role": "assistant", "content": response}
            ]
        )
        
        return {
            "response": response,
            "agent_name": agent["agent_name"]
        }
    
    async def save_agent(self, agent_id: str) -> Dict:
        """Активация агента"""
        await self.db.update_agent_status(agent_id, "active")
        return {
            "success": True,
            "redirect_url": "/dashboard"
        }
    
    async def get_user_agents(self, user_id: str) -> List[Dict]:
        """Получить агентов пользователя"""
        return await self.db.get_user_agents(user_id)
    
    def _clean_tags(self, text: str) -> str:
        """Удаление служебных тегов"""
        return re.sub(r'\[AGENT_\w+:?[^\]]*\]', '', text).strip()
    
    async def _process_files(self, file_urls: List[str]) -> str:
        """Обработка файлов"""
        return "Файлы обработаны"
