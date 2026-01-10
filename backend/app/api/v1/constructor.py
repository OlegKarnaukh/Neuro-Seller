"""
API для конструктора агентов
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional
import uuid
import re
from datetime import datetime
import json

from app.core.database import get_db
from app.models.user import User, PlanType
from app.models.agent import Agent
from app.services.openai_service import chat_completion, parse_agent_ready_response
from app.prompts import META_AGENT_PROMPT, generate_seller_prompt

# Импорты для парсинга сайтов
import httpx
from bs4 import BeautifulSoup

router = APIRouter()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEMAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Message(BaseModel):
    role: str
    content: str

class ConstructorChatRequest(BaseModel):
    user_id: str
    messages: List[Message]
    files: Optional[List[str]] = []  # URLs файлов
    agent_id: Optional[str] = None  # ID агента для обновления
    
class ConstructorChatResponse(BaseModel):
    response: str
    agent_created: bool
    agent_updated: bool = False
    agent_id: Optional[str] = None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ПАРСИНГ САЙТОВ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def parse_website(url: str) -> Dict:
    """
    Парсит сайт и извлекает информацию о бизнесе
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Извлекаем текст
        text = soup.get_text(separator=' ', strip=True)
        
        # Ограничиваем длину (первые 3000 символов)
        text = text[:3000]
        
        # Извлекаем заголовок
        title = soup.title.string if soup.title else ""
        
        # Извлекаем мета-описание
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        description = meta_desc['content'] if meta_desc and meta_desc.get('content') else ""
        
        return {
            "success": True,
            "url": url,
            "title": title,
            "description": description,
            "content": text
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

async def extract_info_from_website(url: str) -> Dict:
    """
    Парсит сайт и использует GPT для извлечения структурированной информации
    """
    parsed_data = await parse_website(url)
    
    if not parsed_data["success"]:
        return {"error": parsed_data["error"]}
    
    # Используем GPT для структурирования информации
    extraction_prompt = f"""Проанализируй содержимое сайта и извлеки структурированную информацию.

Сайт: {url}
Заголовок: {parsed_data['title']}
Описание: {parsed_data['description']}

Содержимое:
{parsed_data['content']}

Извлеки и структурируй:
1. Тип бизнеса (чем занимается компания)
2. Услуги/товары (список)
3. Цены (если есть)
4. Контакты (телефон, email, адрес)
5. Краткое описание компании

Верни результат СТРОГО в формате JSON:
{{
  "business_type": "...",
  "services": ["...", "..."],
  "prices": {{"название": "цена", ...}},
  "contacts": {{"phone": "...", "email": "...", "address": "..."}},
  "about": "..."
}}

ВАЖНО: Верни только JSON, без дополнительного текста.
"""
    
    try:
        response = await chat_completion(
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.3
        )
        
        # Пытаемся извлечь JSON из ответа
        content = response["content"]
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            extracted_data = json.loads(json_match.group(0))
            extracted_data["website"] = url
            return extracted_data
        else:
            return {"raw_data": content, "website": url}
    
    except Exception as e:
        return {"error": f"Ошибка извлечения данных: {str(e)}", "website": url}

def merge_knowledge_bases(old_kb: dict, new_data: dict) -> dict:
    """
    Объединяет старую и новую базы знаний
    Новые данные дополняют старые, не заменяя их
    """
    merged = old_kb.copy()
    
    # Обновляем простые поля
    for key in ["business_type", "website", "about"]:
        if new_data.get(key):
            merged[key] = new_data[key]
    
    # Объединяем услуги (добавляем новые)
    if new_data.get("services"):
        old_services = merged.get("services", [])
        new_services = new_data["services"]
        
        if isinstance(old_services, list) and isinstance(new_services, list):
            # Добавляем новые услуги
            merged["services"] = old_services + new_services
        else:
            merged["services"] = new_services
    
    # Объединяем цены
    if new_data.get("prices"):
        old_prices = merged.get("prices", {})
        new_prices = new_data["prices"]
        
        if isinstance(old_prices, dict) and isinstance(new_prices, dict):
            old_prices.update(new_prices)
            merged["prices"] = old_prices
        else:
            merged["prices"] = new_prices
    
    # Объединяем контакты
    if new_data.get("contacts"):
        old_contacts = merged.get("contacts", {})
        new_contacts = new_data["contacts"]
        
        if isinstance(old_contacts, dict) and isinstance(new_contacts, dict):
            old_contacts.update(new_contacts)
            merged["contacts"] = old_contacts
        else:
            merged["contacts"] = new_contacts
    
    # Объединяем FAQ
    if new_data.get("faq"):
        old_faq = merged.get("faq", [])
        new_faq = new_data["faq"]
        
        if isinstance(old_faq, list) and isinstance(new_faq, list):
            merged["faq"] = old_faq + new_faq
        else:
            merged["faq"] = new_faq
    
    # Добавляем raw_data
    if new_data.get("raw_data"):
        old_raw = merged.get("raw_data", "")
        merged["raw_data"] = f"{old_raw}\n\n{new_data['raw_data']}".strip()
    
    return merged

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IN-MEMORY STORAGE для истории диалогов
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

conversations: Dict[str, List[Dict]] = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/chat", response_model=ConstructorChatResponse)
async def constructor_chat(
    request: ConstructorChatRequest,
    db: Session = Depends(get_db)
):
    """
    Диалог с мета-агентом для создания или обновления персонализированного агента
    """
    try:
        user_id = request.user_id
        agent_id = request.agent_id
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем/создаём пользователя
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            # Создаём нового пользователя автоматически
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
            
            print(f"✅ Created new user: {user_id}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем режим: создание или обновление
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        update_mode = False
        existing_agent = None
        
        if agent_id:
            # Режим обновления — загружаем существующего агента
            existing_agent = db.query(Agent).filter(
                Agent.id == agent_id,
                Agent.user_id == user_id
            ).first()
            
            if not existing_agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            
            update_mode = True
            print(f"🔄 Update mode: agent {agent_id}")
        else:
            # Режим создания — проверяем сообщение на признаки обновления
            last_message = request.messages[-1].content.lower() if request.messages else ""
            update_keywords = ["добавь к агенту", "обнови агента", "дополни агента", "изменить агента"]
            
            if any(keyword in last_message for keyword in update_keywords):
                # Пытаемся найти последнего созданного агента
                existing_agent = db.query(Agent).filter(
                    Agent.user_id == user_id
                ).order_by(Agent.created_at.desc()).first()
                
                if existing_agent:
                    update_mode = True
                    agent_id = existing_agent.id
                    print(f"🔄 Auto-detected update mode: agent {agent_id}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Загружаем историю диалога
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        conversation_key = f"{user_id}:{agent_id}" if agent_id else user_id
        
        if conversation_key not in conversations:
            conversations[conversation_key] = []
        
        # Обрабатываем новые сообщения
        for msg in request.messages:
            msg_dict = msg.dict()
            if msg_dict not in conversations[conversation_key]:
                conversations[conversation_key].append(msg_dict)
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Если режим обновления — добавляем текущую информацию агента
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        if update_mode and existing_agent:
            current_kb = existing_agent.knowledge_base or {}
            
            # Формируем описание текущей базы знаний
            kb_summary = []
            kb_summary.append(f"**Агент**: {existing_agent.agent_name}")
            kb_summary.append(f"**Бизнес**: {existing_agent.business_type}")
            
            if current_kb.get("services"):
                services = current_kb["services"]
                if isinstance(services, list):
                    kb_summary.append(f"**Услуги**: {', '.join([s.get('name', s) if isinstance(s, dict) else s for s in services[:5]])}")
                else:
                    kb_summary.append(f"**Услуги**: {services}")
            
            if current_kb.get("prices"):
                kb_summary.append(f"**Цены**: указаны")
            
            if current_kb.get("website"):
                kb_summary.append(f"**Сайт**: {current_kb['website']}")
            
            agent_context = f"""[CURRENT_AGENT_DATA]
Ты работаешь в режиме ОБНОВЛЕНИЯ существующего агента.

Текущая информация об агенте:
{chr(10).join(kb_summary)}

Полная база знаний:
{json.dumps(current_kb, ensure_ascii=False, indent=2)}

[END_CURRENT_AGENT_DATA]
"""
            
            # Добавляем контекст в начало диалога (если ещё не добавлен)
            if not any("[CURRENT_AGENT_DATA]" in msg.get("content", "") for msg in conversations[conversation_key]):
                conversations[conversation_key].insert(0, {
                    "role": "system",
                    "content": agent_context
                })
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем наличие URL в последнем сообщении
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        last_message = request.messages[-1].content if request.messages else ""
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, last_message)
        
        # Если найден URL, парсим сайт
        if urls:
            url = urls[0]
            print(f"🔍 Парсинг сайта: {url}")
            
            website_data = await extract_info_from_website(url)
            
            # Добавляем информацию о сайте в контекст
            if "error" not in website_data:
                site_info_message = f"""[ИНФОРМАЦИЯ С САЙТА {url}]

Тип бизнеса: {website_data.get('business_type', 'не определено')}

Услуги/Товары:
{', '.join(website_data.get('services', []))}

Цены:
{json.dumps(website_data.get('prices', {}), ensure_ascii=False, indent=2)}

Контакты:
{json.dumps(website_data.get('contacts', {}), ensure_ascii=False, indent=2)}

О компании:
{website_data.get('about', '')}

[КОНЕЦ ИНФОРМАЦИИ С САЙТА]
"""
                conversations[conversation_key].append({
                    "role": "system",
                    "content": site_info_message
                })
                
                print(f"✅ Сайт успешно обработан")
            else:
                print(f"❌ Ошибка парсинга сайта: {website_data.get('error')}")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Формируем контекст для GPT
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        messages = [
            {"role": "system", "content": META_AGENT_PROMPT}
        ] + conversations[conversation_key]
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Запрос к OpenAI
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        response = await chat_completion(messages=messages, temperature=0.7)
        response_text = response["content"]
        
        print(f"📨 Ответ мета-агента: {response_text[:200]}...")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем на создание нового агента
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        agent_data = parse_agent_ready_response(response_text)
        
        if agent_data and not update_mode:
            print(f"🎉 Создаём нового агента: {agent_data}")
            
            # Создаём агента
            agent_name = agent_data["agent_name"]
            business_type = agent_data["business_type"]
            knowledge_base = agent_data["knowledge_base"]
            
            # Генерируем промпт для агента
            system_prompt = generate_seller_prompt(
                agent_name=agent_name,
                business_type=business_type,
                knowledge_base=knowledge_base
            )
            
            # Сохраняем агента в БД
            new_agent = Agent(
                id=str(uuid.uuid4()),
                user_id=user_id,
                agent_name=agent_name.capitalize(),
                business_type=business_type,
                persona=agent_name,
                knowledge_base=knowledge_base,
                system_prompt=system_prompt,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)
            
            print(f"✅ Агент создан с ID: {new_agent.id}")
            
            # Очищаем историю диалога
            conversations[conversation_key] = []
            
            return ConstructorChatResponse(
                response=f"🎉 Агент '{agent_name.capitalize()}' успешно создан!\n\nID агента: {new_agent.id}\n\nТеперь вы можете протестировать его работу или подключить к каналам (Telegram, WhatsApp, VK).",
                agent_created=True,
                agent_updated=False,
                agent_id=new_agent.id
            )
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Проверяем на обновление агента
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        # Ищем тег ---AGENT-UPDATE---
        if "---AGENT-UPDATE---" in response_text and update_mode and existing_agent:
            print(f"🔄 Обновляем агента: {agent_id}")
            
            # Парсим данные обновления (аналогично parse_agent_ready_response)
            update_match = re.search(r"---AGENT-UPDATE---(.*?)---", response_text, re.DOTALL)
            
            if update_match:
                update_content = update_match.group(1).strip()
                
                # Извлекаем DATA
                data_match = re.search(r"DATA:\s*(.+)", update_content, re.DOTALL)
                
                if data_match:
                    data_str = data_match.group(1).strip()
                    json_match = re.search(r'\{.*\}', data_str, re.DOTALL)
                    
                    if json_match:
                        new_kb_data = json.loads(json_match.group(0))
                        
                        # Объединяем старую и новую базы знаний
                        old_kb = existing_agent.knowledge_base or {}
                        updated_kb = merge_knowledge_bases(old_kb, new_kb_data)
                        
                        # Регенерируем промпт
                        updated_prompt = generate_seller_prompt(
                            agent_name=existing_agent.persona,
                            business_type=existing_agent.business_type,
                            knowledge_base=updated_kb
                        )
                        
                        # Обновляем агента в БД
                        existing_agent.knowledge_base = updated_kb
                        existing_agent.system_prompt = updated_prompt
                        existing_agent.updated_at = datetime.utcnow()
                        
                        db.commit()
                        db.refresh(existing_agent)
                        
                        print(f"✅ Агент обновлён: {agent_id}")
                        
                        # Очищаем историю диалога
                        conversations[conversation_key] = []
                        
                        return ConstructorChatResponse(
                            response=f"✅ Агент '{existing_agent.agent_name}' успешно обновлён!\n\nДобавлена новая информация в базу знаний. Промпт агента перегенерирован.",
                            agent_created=False,
                            agent_updated=True,
                            agent_id=existing_agent.id
                        )
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Сохраняем ответ ассистента в историю
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        conversations[conversation_key].append({
            "role": "assistant",
            "content": response_text
        })
        
        return ConstructorChatResponse(
            response=response_text,
            agent_created=False,
            agent_updated=False,
            agent_id=agent_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка в constructor_chat: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
