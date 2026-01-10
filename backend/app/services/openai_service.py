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
    
    Или (без закрывающего тега):
    ---AGENT-READY---
    NAME: Виктория
    TYPE: Салон красоты
    DATA: {JSON}
    
    """
    if "---AGENT-READY---" not in response_text:
        return None
    
    try:
        # Извлекаем блок между ---AGENT-READY--- и --- (или до конца, если нет ---)
        pattern = r"---AGENT-READY---(.*?)(?:---|$)"
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
            
            # Убираем всё после JSON (если есть текст после)
            # Ищем первый символ { и последний }
            json_start = data_str.find('{')
            if json_start != -1:
                # Находим соответствующую закрывающую скобку
                brace_count = 0
                json_end = -1
                for i in range(json_start, len(data_str)):
                    if data_str[i] == '{':
                        brace_count += 1
                    elif data_str[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                
                if json_end != -1:
                    data_str = data_str[json_start:json_end]
            
            # Пытаемся распарсить как JSON
            try:
                raw_kb = json.loads(data_str)
                
                # Нормализуем структуру (преобразуем русские ключи в английские)
                knowledge_base = normalize_knowledge_base(raw_kb)
                
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON parse error: {e}")
                print(f"Raw data_str: {data_str}")
                # Если парсинг не удался, сохраняем как raw_data
                knowledge_base = {"raw_data": data_str}
            
            agent_data["knowledge_base"] = knowledge_base
        
        # Проверяем обязательные поля
        if not agent_data.get("agent_name") or not agent_data.get("business_type"):
            print(f"⚠️ Missing required fields: agent_name={agent_data.get('agent_name')}, business_type={agent_data.get('business_type')}")
            return None
        
        print(f"✅ Parsed agent data: {agent_data}")
        return agent_data
    
    except Exception as e:
        print(f"❌ Error parsing agent ready response: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def normalize_knowledge_base(raw_kb: dict) -> dict:
    """
    Нормализует базу знаний — преобразует русские ключи в английские
    и приводит к стандартному формату
    """
    normalized = {}
    
    # Маппинг русских ключей на английские
    key_mapping = {
        "услуги": "services",
        "товары": "services",
        "цены": "prices",
        "контакты": "contacts",
        "о компании": "about",
        "описание": "about",
        "сайт": "website",
        "стиль": "style",
        "faq": "faq",
        "частые вопросы": "faq"
    }
    
    for key, value in raw_kb.items():
        # Приводим ключ к нижнему регистру
        key_lower = key.lower().strip()
        
        # Ищем соответствие в маппинге
        english_key = key_mapping.get(key_lower, key_lower)
        
        # Специальная обработка для услуг
        if english_key == "services":
            if isinstance(value, dict):
                # Преобразуем {"Услуга": "Цена"} в [{"name": "Услуга", "price": "Цена"}]
                services_list = []
                for service_name, service_price in value.items():
                    services_list.append({
                        "name": service_name,
                        "price": service_price
                    })
                normalized["services"] = services_list
            elif isinstance(value, list):
                normalized["services"] = value
            else:
                normalized["services"] = [{"name": str(value), "price": "цена по запросу"}]
        
        # Специальная обработка для цен
        elif english_key == "prices":
            if isinstance(value, dict):
                normalized["prices"] = value
            else:
                normalized["prices"] = {"общее": str(value)}
        
        # Игнорируем "Стиль" — это не часть базы знаний
        elif english_key == "style":
            continue
        
        # Остальные поля копируем как есть
        else:
            normalized[english_key] = value
    
    return normalized
