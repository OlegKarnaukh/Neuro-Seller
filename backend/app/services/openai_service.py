"""
Сервис для работы с OpenAI API
"""
import os
import json
import re
import logging
from typing import List, Dict, Optional, Any
from openai import AsyncOpenAI

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация АСИНХРОННОГО OpenAI клиента
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def chat_completion(
    messages: List[Dict[str, str]], 
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> str:
    """
    Отправляет запрос к OpenAI API и возвращает ответ.
    
    Args:
        messages: Список сообщений в формате [{"role": "user", "content": "..."}]
        model: Модель для использования (по умолчанию gpt-4o-mini)
        temperature: Температура генерации (0-1)
        max_tokens: Максимальное количество токенов в ответе
    
    Returns:
        Текстовый ответ от модели
    """
    try:
        logger.info(f"🤖 Отправка запроса к OpenAI (model={model})")
        logger.info(f"📝 Количество сообщений: {len(messages)}")
        
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        content = response.choices[0].message.content
        logger.info(f"✅ Получен ответ от OpenAI ({len(content)} символов)")
        
        return content
    
    except Exception as e:
        logger.error(f"❌ Ошибка при обращении к OpenAI: {e}")
        raise


def parse_agent_ready_response(content: str) -> Optional[Dict[str, Any]]:
    """
    Парсит ответ мета-агента и извлекает данные для создания агента.
    
    Ожидаемый формат:
    ---AGENT-READY---
    NAME: Виктория
    TYPE: Салон красоты
    DATA: {...}
    ---
    
    Или инлайн-формат:
    ---AGENT-READY--- NAME: виктория TYPE: Салон красоты DATA: {...}
    """
    
    # Ищем тег ---AGENT-READY---
    if "---AGENT-READY---" not in content:
        logger.info("❌ Тег ---AGENT-READY--- не найден в ответе")
        return None
    
    logger.info("✅ Тег ---AGENT-READY--- найден!")
    
    try:
        # Извлекаем блок после тега ---AGENT-READY---
        # Убираем всё до тега
        agent_block = content.split("---AGENT-READY---", 1)[1]
        
        # Убираем закрывающий тег ---, если есть
        if "---" in agent_block:
            agent_block = agent_block.split("---")[0]
        
        # Убираем эмодзи и лишний текст после DATA
        # Оставляем только NAME, TYPE, DATA
        agent_block = agent_block.strip()
        
        logger.info(f"📋 Извлечённый блок (первые 300 символов):\n{agent_block[:300]}")
        
        # Извлекаем NAME
        name_match = re.search(r'NAME:\s*([^\n\r]+?)(?:\s+TYPE:|$)', agent_block, re.IGNORECASE)
        if not name_match:
            logger.error("❌ NAME не найден")
            return None
        
        agent_name = name_match.group(1).strip()
        logger.info(f"✅ agent_name: '{agent_name}'")
        
        # Извлекаем TYPE
        type_match = re.search(r'TYPE:\s*([^\n\r]+?)(?:\s+DATA:|$)', agent_block, re.IGNORECASE)
        if not type_match:
            logger.error("❌ TYPE не найден")
            return None
        
        business_type = type_match.group(1).strip()
        logger.info(f"✅ business_type: '{business_type}'")
        
        # Извлекаем DATA (JSON или текст)
        data_match = re.search(r'DATA:\s*(.+?)(?:\n🎉|\n---|$)', agent_block, re.IGNORECASE | re.DOTALL)
        if not data_match:
            logger.error("❌ DATA не найден")
            return None
        
        data_raw = data_match.group(1).strip()
        
        # Ищем первый '{' и соответствующий '}'
        json_start = data_raw.find('{')
        if json_start == -1:
            logger.error("❌ JSON не найден в DATA")
            return None
        
        # Находим соответствующую закрывающую скобку
        brace_count = 0
        json_end = -1
        for i in range(json_start, len(data_raw)):
            if data_raw[i] == '{':
                brace_count += 1
            elif data_raw[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1:
            logger.error("❌ Не найдена закрывающая скобка JSON")
            return None
        
        json_str = data_raw[json_start:json_end]
        logger.info(f"📦 JSON строка (первые 200 символов): {json_str[:200]}")
        
        # Парсим JSON
        try:
            knowledge_base = json.loads(json_str)
            logger.info("✅ knowledge_base успешно распарсена")
            logger.info(f"   Ключи: {list(knowledge_base.keys())}")
            
            # Нормализуем базу знаний (русские ключи → английские)
            knowledge_base = normalize_knowledge_base(knowledge_base)
            
            return {
                "agent_name": agent_name.capitalize(),
                "business_type": business_type,
                "knowledge_base": knowledge_base
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            logger.error(f"   JSON строка: {json_str}")
            return None
    
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга AGENT-READY: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def parse_agent_update_response(content: str) -> Optional[Dict[str, Any]]:
    """
    Парсит ответ мета-агента для обновления существующего агента.
    
    Ожидаемый формат:
    ---AGENT-UPDATE---
    DATA: {...}
    ---AGENT-UPDATE---
    """
    
    # Ищем тег ---AGENT-UPDATE---
    if "---AGENT-UPDATE---" not in content:
        logger.info("❌ Тег ---AGENT-UPDATE--- не найден в ответе")
        return None
    
    logger.info("✅ Тег ---AGENT-UPDATE--- найден!")
    
    try:
        # Извлекаем блок между тегами
        agent_block = content.split("---AGENT-UPDATE---")[1]
        
        # Убираем закрывающий тег
        if "---AGENT-UPDATE---" in agent_block:
            agent_block = agent_block.split("---AGENT-UPDATE---")[0]
        
        agent_block = agent_block.strip()
        
        logger.info(f"📋 Извлечённый UPDATE блок (первые 300 символов):\n{agent_block[:300]}")
        
        # Извлекаем DATA (JSON)
        data_match = re.search(r'DATA:\s*(.+?)$', agent_block, re.IGNORECASE | re.DOTALL)
        if not data_match:
            logger.error("❌ DATA не найден в UPDATE")
            return None
        
        data_raw = data_match.group(1).strip()
        
        # Ищем JSON
        json_start = data_raw.find('{')
        if json_start == -1:
            logger.error("❌ JSON не найден в UPDATE DATA")
            return None
        
        # Находим закрывающую скобку
        brace_count = 0
        json_end = -1
        for i in range(json_start, len(data_raw)):
            if data_raw[i] == '{':
                brace_count += 1
            elif data_raw[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1:
            logger.error("❌ Не найдена закрывающая скобка JSON в UPDATE")
            return None
        
        json_str = data_raw[json_start:json_end]
        logger.info(f"📦 UPDATE JSON (первые 200 символов): {json_str[:200]}")
        
        # Парсим JSON
        try:
            update_data = json.loads(json_str)
            logger.info("✅ UPDATE data успешно распарсена")
            logger.info(f"   Ключи для обновления: {list(update_data.keys())}")
            
            # Нормализуем базу знаний
            update_data = normalize_knowledge_base(update_data)
            
            return {
                "update_data": update_data
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга UPDATE JSON: {e}")
            logger.error(f"   JSON строка: {json_str}")
            return None
    
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга AGENT-UPDATE: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def normalize_knowledge_base(kb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализует базу знаний: русские ключи → английские.
    Преобразует структуру услуг в единый формат.
    Поддерживает новые маркетинговые поля v3.0.
    """
    normalized = {}
    
    # Маппинг русских ключей на английские
    key_mapping = {
        "услуги": "services",
        "цены": "prices",
        "товары": "products",
        "о_бизнесе": "about",
        "контакты": "contacts",
        "faq": "faq",
        "сайт": "website",
        "дополнительно": "additional_info",
        # Новые маркетинговые поля v3.0
        "целевая_аудитория": "target_audience",
        "ца": "target_audience",
        "ключевая_боль": "key_pain",
        "боль": "key_pain",
        "утп": "usp",
        "уникальное_предложение": "usp",
        "возражения": "objections",
        "акции": "promo",
        "спецпредложения": "promo",
        "преимущества": "advantages"
    }
    
    for key, value in kb.items():
        # Переводим ключ
        eng_key = key_mapping.get(key.lower(), key)
        
        # Обрабатываем услуги
        if eng_key == "services":
            # Если services — это объект {"название": "цена"}, преобразуем в список
            if isinstance(value, dict):
                normalized["services"] = [
                    {"name": name, "price": price}
                    for name, price in value.items()
                ]
            # Если уже список — оставляем как есть
            elif isinstance(value, list):
                normalized["services"] = value
        else:
            normalized[eng_key] = value
    
    return normalized
