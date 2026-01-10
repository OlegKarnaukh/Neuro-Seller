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
    Parse META_AGENT response for [AGENT_READY] tag and extract data.
    
    Returns:
        Dict with agent_name, business_type, knowledge_base or None
    """
    if "[AGENT_READY]" not in response_text:
        return None
    
    # Extract data between tags
    import re
    
    agent_name_match = re.search(r'\[AGENT_NAME\]:\s*(.+)', response_text)
    business_type_match = re.search(r'\[BUSINESS_TYPE\]:\s*(.+)', response_text)
    knowledge_base_match = re.search(r'\[KNOWLEDGE_BASE\]:\s*(\{.+\})', response_text, re.DOTALL)
    
    if not (agent_name_match and business_type_match):
        return None
    
    # Parse knowledge base JSON
    knowledge_base = {}
    if knowledge_base_match:
        try:
            import json
            knowledge_base = json.loads(knowledge_base_match.group(1))
        except:
            pass
    
    return {
        "agent_name": agent_name_match.group(1).strip(),
        "business_type": business_type_match.group(1).strip(),
        "knowledge_base": knowledge_base
    }
