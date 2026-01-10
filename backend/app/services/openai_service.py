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
    NAME: виктория
    TYPE: Салон красоты
    DATA: {"services": [...]}
    ---
    """
    if "---AGENT-READY---" not in response_text:
        return None
    
    try:
        # Извлекаем блок между ---AGENT-READY--- и ---
        pattern = r"---AGENT-READY---(.*?)---"
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            print("⚠️ No match found for ---AGENT-READY--- block")
            return None
        
        content = match.group(1).strip()
        print(f"📋 Extracted content:\n{content}\n")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Извлекаем NAME (только первое слово)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        name_match = re.search(r"NAME:\s*(\S+)", content, re.IGNORECASE)
        if not name_match:
            print("⚠️ NAME not found")
            return None
        
        agent_name = name_match.group(1).strip().lower()
        print(f"✅ agent_name: '{agent_name}'")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Извлекаем TYPE (всё до переноса или до DATA)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        type_match = re.search(r"TYPE:\s*([^\n]+?)(?:\n|DATA:|$)", content, re.IGNORECASE)
        if not type_match:
            print("⚠️ TYPE not found")
            return None
        
        business_type = type_match.group(1).strip()
        # Убираем "DATA:" если попало
        business_type = re.sub(r'\s*DATA:.*', '', business_type, flags=re.IGNORECASE).strip()
        print(f"✅ business_type: '{business_type}'")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Извлекаем DATA (JSON)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        data_match = re.search(r"DATA:\s*(\{.+?\})\s*(?:\n|$)", content, re.DOTALL | re.IGNORECASE)
        if not data_match:
            print("⚠️ DATA not found")
            return None
        
        data_str = data_match.group(1).strip()
        print(f"📦 JSON string (first 200 chars): {data_str[:200]}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Парсим JSON
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        try:
            raw_kb = json.loads(data_str)
            knowledge_base = normalize_knowledge_base(raw_kb)
            print(f"✅ knowledge_base parsed successfully")
            print(f"   Keys: {list(knowledge_base.keys())}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON parse error: {e}")
            print(f"   Raw JSON: {data_str}")
            knowledge_base = {"raw_data": data_str}
        
        return {
            "agent_name": agent_name,
            "business_type": business_type,
            "knowledge_base": knowledge_base
        }
    
    except Exception as e:
        print(f"❌ Error in parse_agent_ready_response: {str(e)}")
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
        "частые вопросы": "faq",
        "персона агента": "persona_info",
        "персона": "persona_info"
    }
    
    for key, value in raw_kb.items():
        # Приводим ключ к нижнему регистру
        key_lower = key.lower().strip()
        
        # Ищем соответствие в маппинге
        english_key = key_mapping.get(key_lower, key_lower)
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Специальная обработка для услуг
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
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
                # Уже список — проверяем формат
                normalized_services = []
                for item in value:
                    if isinstance(item, dict):
                        normalized_services.append(item)
                    else:
                        normalized_services.append({
                            "name": str(item),
                            "price": "цена по запросу"
                        })
                normalized["services"] = normalized_services
            else:
                normalized["services"] = [{"name": str(value), "price": "цена по запросу"}]
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Специальная обработка для цен
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        elif english_key == "prices":
            if isinstance(value, dict):
                normalized["prices"] = value
            else:
                normalized["prices"] = {"общее": str(value)}
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Игнорируем служебные поля
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        elif english_key in ["style", "persona_info"]:
            # Эти поля не нужны в базе знаний агента
            continue
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Остальные поля копируем как есть
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        else:
            normalized[english_key] = value
    
    return normalized
