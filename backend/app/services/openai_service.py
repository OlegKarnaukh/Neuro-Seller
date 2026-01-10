"""
OpenAI Service for chat completions
"""
from openai import AsyncOpenAI
from typing import List, Dict
from app.core.config import settings

# Initialize client
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def chat_completion(
    messages: List[Dict[str, str]],
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 2000
) -> Dict:
    """
    Call OpenAI Chat Completion API
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model name (default from settings)
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        
    Returns:
        Dict with 'content', 'tokens_used', 'model'
    """
    if model is None:
        model = settings.OPENAI_MODEL
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        return {
            "content": response.choices[0].message.content,
            "tokens_used": response.usage.total_tokens,
            "model": model
        }
        
    except Exception as e:
        print(f"❌ OpenAI API Error: {e}")
        raise


async def parse_agent_ready_response(response_text: str) -> Dict:
    """
    Parse META_AGENT response for ---AGENT-READY--- tag and extract data.
    
    Returns:
        Dict with agent_name, business_type, knowledge_base or None
    """
    if "---AGENT-READY---" not in response_text:
        return None
    
    # Extract data between markers
    import re
    
    # Extract agent name
    name_match = re.search(r'NAME:\s*(.+)', response_text)
    # Extract business type
    type_match = re.search(r'TYPE:\s*(.+)', response_text)
    # Extract data
    data_match = re.search(r'DATA:\s*(.+)', response_text)
    
    if not (name_match and type_match):
        return None
    
    agent_name = name_match.group(1).strip()
    business_type = type_match.group(1).strip()
    
    # Parse data into knowledge_base
    knowledge_base = {}
    if data_match:
        data_str = data_match.group(1).strip()
        
        # Try to extract structured info from text
        # Look for website
        website_match = re.search(r'(?:сайт|website)[:\s]+([^\s,]+)', data_str, re.IGNORECASE)
        if website_match:
            knowledge_base["website"] = website_match.group(1)
        
        # Extract everything as raw text for now
        knowledge_base["raw_data"] = data_str
    
    return {
        "agent_name": agent_name.lower(),
        "business_type": business_type,
        "knowledge_base": knowledge_base
    }
