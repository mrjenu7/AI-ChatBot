from typing import List, Dict
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.rag_service import retrieve_relevant_context
from app.services.company_guard import classify_scope, refusal, clarification
from app.services.language_service import (
    detect_language_profile,
    language_contract,
    localized_connection_error,
)


def _get_client() -> AsyncOpenAI:
    headers = {}
    if "googleapis.com" in settings.openai_base_url and settings.openai_api_key:
        headers["x-goog-api-key"] = settings.openai_api_key

    return AsyncOpenAI(
        api_key=settings.openai_api_key or "missing_key",
        base_url=settings.openai_base_url,
        default_headers=headers if headers else None,
    )


async def generate_reply(messages: List[Dict[str, str]]) -> str:
    """Compatibility helper using the same latest-message language contract as LangGraph."""
    latest_user_query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            latest_user_query = msg.get("content", "")
            break

    profile = detect_language_profile(latest_user_query)
    scope = await classify_scope(latest_user_query, messages[:-1])
    if scope == "OUT_OF_SCOPE":
        return refusal(profile)
    if scope == "AMBIGUOUS":
        return clarification(profile)
    if not settings.has_openai_api_key:
        return localized_connection_error(profile)

    try:
        rag_context = retrieve_relevant_context(latest_user_query)
        prompt = (
            f"{settings.system_prompt}\n\n"
            f"RESPONSE LANGUAGE CONTRACT: {language_contract(profile)}\n"
            "Understand the user's message in whatever language they use, but always answer ONLY in English. "
            "Do not reply in the user's language if it is not English. All explanations, greetings, and answers must be in English.\n\n"
            "=== VERIFIED WE3VISION COMPANY KNOWLEDGE BASE ===\n"
            f"{rag_context}\n"
            "=================================================\n"
            "STRICT DOMAIN BOUNDARY:\n"
            "1. Answer ONLY questions related to We3vision Private Limited or polite greetings.\n"
            "2. If the user asks about anything unrelated to We3vision (such as general knowledge, sports, celebrities, math, non-company coding, etc.), "
            "DO NOT answer it. Politely decline in English, explaining that you are dedicated exclusively to We3vision questions.\n"
            "3. Use only approved company facts. If a company-specific fact is unavailable, say so in English "
            "and offer info@we3vision.com / +91 7383216096."
        )
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": prompt}] + messages,
            temperature=settings.llm_temperature,
            max_tokens=min(settings.llm_max_tokens, 300),
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[LLM Error]: {exc}")
        return localized_connection_error(profile)
