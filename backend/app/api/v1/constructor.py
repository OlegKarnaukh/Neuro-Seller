import json
import re
import logging
import httpx
from typing import List, Dict, Optional, Any
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from bs4 import BeautifulSoup

from database import get_db
from models import User, Agent, PlanType
from prompts import META_AGENT_PROMPT, generate_seller_prompt
from services.openai_service import chat_completion, parse_agent_ready_response

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Хранилище для истории диалогов (в памяти)
conversations: Dict[str, List[Dict[str, str]]] = {}


# ============================================================================
# МОДЕЛИ PYDANTIC
# ============================================================================

class Message(BaseModel):
    role: str
    content: str


class ConstructorChatRequest(BaseModel):
    user_id: str
    agent_id: Optional[str] = None
    messages: List[Dict[str, str]]


class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool
    agent_updated: bool
    agent_id: Optional[str] = None


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def parse_website(url: str) -> Dict[str, Any]:
    """
    Парсит сайт и возвращает его содержимое.
    
    Args:
        url: URL сайта для парсинга
    
    Returns:
        Словарь с данными сайта:
        {
            "success": bool,
            "url": str,
            "title": str,
            "description": str,
            "content": str
        }
    """
    try:
        logger.info(f"🌐 Парсинг сайта: {url}")
        
        # Отправляем запрос с таймаутом
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        
        # Парсим HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Извлекаем заголовок
        title = soup.find('title')
        title_text = title.get_text().strip() if title else ""
        
        # Извлекаем описание
        description = soup.find('meta', attrs={'name': 'description'})
        description_text = description.get('content', '').strip() if description else ""
        
        # Извлекаем текстовый контент
        text = soup.get_text()
        
        # Очищаем текст от лишних пробелов и переносов строк
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # Ограничиваем длину контента
        content = text[:3000] if len(text) > 3000 else text
        
        logger.info(f"✅ Сайт успешно спарсен: {title_text}")
        
        return {
            "success": True,
            "url": url,
            "title": title_text,
            "description": description_text,
            "content": content
        }
    
    except httpx.TimeoutException:
        logger.error(f"❌ Таймаут при парсинге сайта: {url}")
        return {"success": False, "url": url, "error": "Timeout"}
    
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP ошибка при парсинге сайта: {e.response.status_code}")
        return {"success": False, "url": url, "error": f"HTTP {e.response.status_code}"}
    
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге сайта: {e}")
        return {"success": False, "url": url, "error": str(e)}


def extract_info_from_website(url: str) -> Dict[str, Any]:
    """
    Извлекает структурированную информацию с сайта через GPT.
    
    Args:
        url: URL сайта для парсинга
    
    Returns:
        Словарь с информацией о бизнесе
    """
    
    # Парсим сайт
    site_data = parse_website(url)
    
    if not site_data["success"]:
        logger.error(f"❌ Не удалось спарсить сайт: {url}")
        return {}
    
    # Формируем промпт для GPT
    prompt = f"""
Проанализируй содержимое сайта и извлеки следующую информацию в формате JSON:

{{
  "business_type": "тип бизнеса (например: Салон красоты, Ресторан, Магазин одежды)",
  "services": [
    {{"name": "название услуги или товара", "price": "цена (если указана)"}}
  ],
  "about": "краткое описание бизнеса",
  "contacts": {{
    "phone": "телефон (если есть)",
    "email": "email (если есть)",
    "address": "адрес (если есть)"
  }}
}}

ВАЖНО:
- Верни только JSON, без дополнительного текста
- Если какое-то поле не найдено, оставь его пустым
- Для services укажи максимум 5-7 основных услуг/товаров
- Для цен сохраняй оригинальный формат (например: "1500 руб", "от 3000 руб")

Содержимое сайта:
{site_data["content"][:3000]}
"""
    
    # Вызываем GPT
    response = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o-mini",
        temperature=0.3
    )
    
    logger.info(f"📝 Ответ GPT (первые 200 символов): {response[:200]}")
    
    # Парсим JSON из ответа
    try:
        # Ищем первый '{' и последний '}'
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        
        if json_start == -1 or json_end <= json_start:
            logger.error("❌ JSON не найден в ответе GPT")
            logger.error(f"   Ответ: {response}")
            return {}
        
        json_str = response[json_start:json_end]
        logger.info(f"📦 Извлечённый JSON: {json_str[:200]}")
        
        site_info = json.loads(json_str)
        logger.info(f"✅ Информация с сайта успешно извлечена")
        logger.info(f"   Ключи: {list(site_info.keys())}")
        
        return site_info
    
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        logger.error(f"   JSON строка: {json_str[:200]}")
        return {}
    
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


def merge_knowledge_bases(old_kb: Dict[str, Any], new_kb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Объединяет две базы знаний.
    
    Args:
        old_kb: Старая база знаний
        new_kb: Новая база знаний
    
    Returns:
        Объединённая база знаний
    """
    merged = old_kb.copy()
    
    # Объединяем услуги
    if "services" in new_kb:
        if "services" not in merged:
            merged["services"] = []
        
        # Добавляем новые услуги (избегаем дубликатов по имени)
        existing_names = {s.get("name", "").lower() for s in merged["services"]}
        
        for service in new_kb["services"]:
            if service.get("name", "").lower() not in existing_names:
                merged["services"].append(service)
                existing_names.add(service.get("name", "").lower())
    
    # Обновляем цены
    if "prices" in new_kb:
        merged["prices"] = new_kb["prices"]
    
    # Дополняем FAQ
    if "faq" in new_kb:
        if "faq" not in merged:
            merged["faq"] = []
        merged["faq"].extend(new_kb["faq"])
    
    # Обновляем остальные поля
    for key in ["about", "contacts", "website", "additional_info"]:
        if key in new_kb:
            merged[key] = new_kb[key]
    
    return merged


# ============================================================================
# API ЭНДПОИНТ
# ============================================================================

@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для общения с мета-агентом конструктора.
    
    Поддерживает:
    - Создание нового агента
    - Обновление существующего агента
    - Парсинг сайтов для извлечения информации
    """
    
    try:
        user_id = request.user_id
        agent_id = request.agent_id
        new_messages = request.messages
        
        # 1. ПРОВЕРКА/СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            logger.info(f"👤 Пользователь {user_id} не найден. Создаём нового...")
            
            user = User(
                id=user_id,
                email=f"{user_id}@neuro-seller.local",
                plan=PlanType.FREE,
                credits_balance=1000,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(user)
            db.commit()
            db.refresh(user)
            
            logger.info(f"✅ Создан новый пользователь: {user.email}")
        
        # 2. ОПРЕДЕЛЕНИЕ РЕЖИМА (создание или обновление агента)
        update_mode = False
        
        if agent_id:
            update_mode = True
            logger.info(f"🔄 Режим обновления агента: {agent_id}")
        else:
            # Проверяем последнее сообщение на ключевые слова обновления
            if new_messages:
                last_content = new_messages[-1].get("content", "").lower()
                update_keywords = ["добавь к агенту", "обнови агента", "дополни агента", "изменить агента"]
                
                if any(keyword in last_content for keyword in update_keywords):
                    update_mode = True
                    logger.info("🔄 Обнаружен запрос на обновление агента")
        
        # 3. ЗАГРУЗКА ИСТОРИИ ДИАЛОГА
        conversation_key = f"{user_id}:{agent_id}" if agent_id else user_id
        
        if conversation_key not in conversations:
            conversations[conversation_key] = []
        
        # Добавляем новые сообщения в историю
        conversations[conversation_key].extend(new_messages)
        
        # 4. ПАРСИНГ САЙТА (если есть URL в последнем сообщении)
        if new_messages:
            last_message = new_messages[-1].get("content", "")
            
            # Ищем URL в сообщении
            url_pattern = r'https?://[^\s]+'
            urls = re.findall(url_pattern, last_message)
            
            if urls:
                site_url = urls[0]
                logger.info(f"🌐 Парсинг сайта: {site_url}")
                
                # Парсим сайт
                site_data = parse_website(site_url)
                
                if site_data["success"]:
                    # Извлекаем информацию через GPT
                    site_info = extract_info_from_website(site_url)
                    
                    # Добавляем информацию о сайте в контекст
                    site_context = f"""
[ИНФОРМАЦИЯ С САЙТА {site_url}]
{json.dumps(site_info, ensure_ascii=False, indent=2)}
[КОНЕЦ ИНФОРМАЦИИ С САЙТА]
"""
                    
                    conversations[conversation_key].append({
                        "role": "system",
                        "content": site_context
                    })
                    
                    logger.info(f"✅ Информация с сайта добавлена в контекст")
        
        # 5. ФОРМИРОВАНИЕ КОНТЕКСТА ДЛЯ ОБНОВЛЕНИЯ АГЕНТА (если режим обновления)
        if update_mode and agent_id:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            
            if agent:
                current_agent_data = f"""
[CURRENT_AGENT_DATA]
Имя агента: {agent.agent_name}
Тип бизнеса: {agent.business_type}
Текущая база знаний:
{json.dumps(agent.knowledge_base, ensure_ascii=False, indent=2)}
[END_CURRENT_AGENT_DATA]
"""
                
                # Вставляем информацию об агенте в начало диалога
                conversations[conversation_key].insert(0, {
                    "role": "system",
                    "content": current_agent_data
                })
        
        # 6. ФОРМИРОВАНИЕ КОНТЕКСТА ДЛЯ OPENAI
        context = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ] + conversations[conversation_key]
        
        # 7. ВЫЗОВ OPENAI
        assistant_response = chat_completion(
            messages=context,
            model="gpt-4o-mini",
            temperature=0.7
        )
        
        # 8. ОБРАБОТКА ТЕГА ---AGENT-UPDATE--- (если режим обновления)
        if "---AGENT-UPDATE---" in assistant_response and agent_id:
            logger.info("🔄 Обнаружен тег ---AGENT-UPDATE---")
            
            # Парсим обновление
            update_data = parse_agent_ready_response(assistant_response)
            
            if update_data:
                agent = db.query(Agent).filter(Agent.id == agent_id).first()
                
                if agent:
                    # Объединяем базы знаний
                    merged_kb = merge_knowledge_bases(
                        agent.knowledge_base,
                        update_data["knowledge_base"]
                    )
                    
                    # Обновляем агента
                    agent.knowledge_base = merged_kb
                    agent.system_prompt = generate_seller_prompt(
                        agent_name=agent.agent_name,
                        business_type=agent.business_type,
                        knowledge_base=merged_kb,
                        persona=agent.persona or "Victoria"
                    )
                    agent.updated_at = datetime.utcnow()
                    
                    db.commit()
                    
                    logger.info(f"✅ Агент {agent_id} обновлён!")
                    
                    # Очищаем историю диалога
                    conversations[conversation_key] = []
                    
                    return ConstructorChatResponse(
                        response=f"✅ Агент '{agent.agent_name}' успешно обновлён!",
                        agent_created=False,
                        agent_updated=True,
                        agent_id=str(agent_id)
                    )
        
        # 9. ОБРАБОТКА ТЕГА ---AGENT-READY--- (создание нового агента)
        agent_data = parse_agent_ready_response(assistant_response)
        
        if agent_data:
            logger.info("✅ Данные агента извлечены, создаём агента...")
            
            # Создаём нового агента
            new_agent = Agent(
                id=uuid4(),
                user_id=user_id,
                agent_name=agent_data["agent_name"],
                business_type=agent_data["business_type"],
                persona="Victoria",  # По умолчанию
                knowledge_base=agent_data["knowledge_base"],
                system_prompt=generate_seller_prompt(
                    agent_name=agent_data["agent_name"],
                    business_type=agent_data["business_type"],
                    knowledge_base=agent_data["knowledge_base"],
                    persona="Victoria"
                ),
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)
            
            logger.info(f"✅ Агент создан! agent_id={new_agent.id}")
            
            # Очищаем историю диалога
            conversations[conversation_key] = []
            
            return ConstructorChatResponse(
                response=f"🎉 Отлично! Агент '{new_agent.agent_name}' для {new_agent.business_type} создан!",
                agent_created=True,
                agent_updated=False,
                agent_id=str(new_agent.id)
            )
        
        # 10. ОБЫЧНЫЙ ОТВЕТ (если агент не готов)
        # Сохраняем ответ ассистента в историю
        conversations[conversation_key].append({
            "role": "assistant",
            "content": assistant_response
        })
        
        return ConstructorChatResponse(
            response=assistant_response,
            agent_created=False,
            agent_updated=False,
            agent_id=None
        )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в constructor_chat: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
