"""
Сервис для работы с OpenAI API
"""
from openai import AsyncOpenAI
from app.core.config import settings
from typing import Dict, Optional, List
import json
import re

# Инициализация клиента
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

async def chat_completion(
    messages: List[Dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> Dict:
    """
    Отправляет запрос к OpenAI API
    """
    try:
        if model is None:
            model = settings.OPENAI_MODEL
        
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        
        return {
            "content": content,
            "tokens_used": tokens_used,
            "model": model
        }
    
    except Exception as e:
        raise Exception(f"OpenAI API error: {str(e)}")

def parse_agent_ready_response(response_text: str) -> Optional[Dict]:
    """
    Парсит ответ агента и извлекает данные для создания агента
    
    Ожидаемый формат:
    ---AGENT-READY---
    NAME: Виктория
    TYPE: Салон красоты
    DATA: {JSON с полной информацией}
    ---
    """
    if "---AGENT-READY---" not in response_text:
        return None
    
    try:
        # Извлекаем блок между ---AGENT-READY--- и ---
        pattern = r"---AGENT-READY---(.*?)---"
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            return None
        
        content = match.group(1).strip()
        
        # Парсим поля
        agent_data = {}
        
        # Извлекаем NAME
        name_match = re.search(r"NAME:\s*(.+)", content)
        if name_match:
            agent_data["agent_name"] = name_match.group(1).strip().lower()
        
        # Извлекаем TYPE
        type_match = re.search(r"TYPE:\s*(.+)", content)
        if type_match:
            agent_data["business_type"] = type_match.group(1).strip()
        
        # Извлекаем DATA (может быть JSON или текст)
        data_match = re.search(r"DATA:\s*(.+)", content, re.DOTALL)
        if data_match:
            data_str = data_match.group(1).strip()
            
            # Пытаемся распарсить как JSON
            try:
                # Ищем JSON-блок
                json_match = re.search(r'\{.*\}', data_str, re.DOTALL)
                if json_match:
                    knowledge_base = json.loads(json_match.group(0))
                else:
                    # Если JSON не найден, сохраняем как raw_data
                    knowledge_base = {"raw_data": data_str}
            except json.JSONDecodeError:
                # Если парсинг не удался, сохраняем как raw_data
                knowledge_base = {"raw_data": data_str}
            
            agent_data["knowledge_base"] = knowledge_base
        
        # Проверяем обязательные поля
        if not agent_data.get("agent_name") or not agent_data.get("business_type"):
            return None
        
        return agent_data
    
    except Exception as e:
        print(f"Error parsing agent ready response: {str(e)}")
        return None
