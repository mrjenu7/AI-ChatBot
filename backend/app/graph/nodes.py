import asyncio
import re
from typing import Any, Dict, List

from app.core.config import settings
from app.graph.state import AgentState
from app.services.supabase_service import append_turn, load_conversation
from app.services.language_service import (
    detect_language_profile,
    language_contract,
    response_matches_language,
)
from app.services.company_guard import classify_scope, refusal, clarification
from app.services.llm_service import _get_client
from app.services.rag_service import (
    build_grounded_fallback_reply,
    get_service_option,
    retrieve_relevant_context,
)


# ============================================================
# NODE 1: DETECT USER LANGUAGE
# ============================================================

async def detect_language_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Detect the language of the latest user message.

    The response language is decided only from the latest
    message, not from previous conversation messages.
    """

    user_message = state.get("message", "")

    language_profile = detect_language_profile(
        user_message
    )

    return {
        "language": language_profile
    }


# ============================================================
# NODE 2: LOAD CURRENT SESSION HISTORY
# ============================================================

async def load_history_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Load conversation history for the current session
    from Supabase.
    """

    user_id = state.get(
        "user_id",
        "",
    )

    session_id = state.get("session_id")

    try:
        today_chat = await asyncio.to_thread(
            load_conversation,
            user_id,
            session_id,
        )

    except Exception as error:
        print(
            f"[Supabase Load Error]: {error}"
        )

        today_chat = []

    history_messages: List[Dict[str, str]] = []

    for turn in today_chat:
        user_content = turn.get("user", "")
        assistant_content = turn.get("assistant", "")

        if user_content:
            history_messages.append({
                "role": "user",
                "content": user_content,
            })

        if assistant_content:
            history_messages.append({
                "role": "assistant",
                "content": assistant_content,
            })

    return {
        "history": history_messages
    }


async def company_scope_node(state: AgentState) -> Dict[str, Any]:
    """Classify with conversation context before RAG."""
    scope = await classify_scope(state.get("message", ""), state.get("history", []))
    language = state.get("language") or detect_language_profile(state.get("message", ""))
    if scope == "OUT_OF_SCOPE":
        return {"scope": scope, "reply": refusal(language)}
    if scope == "AMBIGUOUS":
        return {"scope": scope, "reply": clarification(language)}
    return {"scope": scope}


# ============================================================
# NODE 3: RETRIEVE RAG KNOWLEDGE
# ============================================================

async def retrieve_rag_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Retrieve relevant approved company information
    from the knowledge base.
    """

    user_message = state.get("message", "")
    selected_service_id = state.get("selected_service_id")

    try:
        rag_context = await asyncio.to_thread(
            retrieve_relevant_context,
            user_message,
            selected_service_id=selected_service_id,
        )

    except Exception as error:
        print(f"[RAG Retrieval Error]: {error}")

        rag_context = ""

    return {
        "rag_context": rag_context
    }


# ============================================================
# REMOVE MODEL THINKING TAGS
# ============================================================

def _strip_thinking(reply: str) -> str:
    """
    Remove internal <think>...</think> content if returned
    by the model.
    """

    if not reply:
        return ""

    cleaned_reply = re.sub(
        r"<think>.*?</think>",
        "",
        reply,
        flags=re.DOTALL | re.IGNORECASE,
    )

    return cleaned_reply.strip()


def _bounded_history(history: List[Dict[str, str]], max_chars: int = 2600, max_messages: int = 6) -> List[Dict[str, str]]:
    """Keep recent conversational context within a predictable prompt budget."""
    kept: List[Dict[str, str]] = []
    remaining = max_chars
    for message in reversed(history[-max_messages:]):
        content = str(message.get("content", ""))
        if not content or remaining <= 0:
            continue
        if len(content) > remaining:
            # Skip an oversized older message; preserve recent, complete turns.
            continue
        kept.append({"role": message.get("role", "user"), "content": content})
        remaining -= len(content)
    return list(reversed(kept))


# ============================================================
# REPAIR RESPONSE LANGUAGE
# ============================================================

async def _repair_language(
    client,
    original_user_message: str,
    previous_reply: str,
    language_profile: Dict[str, Any],
) -> str:
    """
    Rewrite the assistant response into clear, natural English
    if it was generated in a non-English language.

    The facts must remain unchanged.
    """

    contract = language_contract(
        language_profile
    )

    repair_messages = [
        {
            "role": "system",
            "content": (
                "You are a language-compliance editor. "
                "Rewrite the previous assistant answer strictly into clear, natural English. "
                "Do not answer in Gujarati, Hindi, or any other non-English language. "
                "Do not add, remove, invent, or change any facts. "
                "Do not explain what you changed. Return only the corrected English answer.\n\n"
                f"{contract}"
            ),
        },
        {
            "role": "user",
            "content": (
                "Latest user message:\n"
                f"{original_user_message}\n\n"
                "Previous assistant answer:\n"
                f"{previous_reply}\n\n"
                "Return only the corrected English answer."
            ),
        },
    ]

    repaired_response = (
        await client.chat.completions.create(
            model=settings.llm_model,
            messages=repair_messages,
            temperature=0.2,
            max_tokens=min(settings.llm_max_tokens, 300),
        )
    )

    repaired_reply = (
        repaired_response
        .choices[0]
        .message
        .content
        or ""
    )

    return _strip_thinking(repaired_reply)


# ============================================================
# NODE 4: GENERATE LLM RESPONSE
# ============================================================

async def generate_response_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Generate a RAG-grounded response and enforce
    the correct response language.
    """

    user_message = state.get("message", "")
    rag_context = state.get("rag_context", "")
    selected_service = get_service_option(state.get("selected_service_id"))
    # A newly selected service starts a focused turn; older topic history can
    # otherwise pull the answer back toward a different service/query.
    history = [] if selected_service else state.get("history", [])

    language_profile = (
        state.get("language")
        or detect_language_profile(user_message)
    )

    contract = language_contract(
        language_profile
    )
    selected_service_instruction = (
        f"USER-SELECTED SERVICE FILTER: {selected_service['title']}. Use this only to focus retrieval; "
        "answer the user's actual question and do not treat selection itself as evidence.\n\n"
        if selected_service else ""
    )

    # Return a safe localized message when API key is missing
    if not settings.has_openai_api_key:
        return {
            "reply": build_grounded_fallback_reply(user_message, rag_context)
        }

    rag_system_prompt = (
        f"{settings.system_prompt}\n\n"
        "LANGUAGE: Understand any input language, but reply only in English.\n"
        "VERIFIED WE3VISION KNOWLEDGE:\n"
        f"{rag_context}\n"
        f"{selected_service_instruction}"
        "Use this retrieved text as the only source for company-specific facts. Keep claims attached to their service; do not infer capabilities from examples or industry descriptions. "
        "If a requested detail is missing, conflicting, or marked unverified, say it needs confirmation. Do not invent or promise features, results, prices, timelines, quotes, availability, or callbacks. "
        "The selected service only focuses retrieval; it is not evidence by itself. For unrelated requests, politely decline and stay focused on We3vision. "
        "Answer the user's question directly in 2-4 concise sentences, ask at most one useful follow-up question, and use plain English text without Markdown."
    )

    full_messages = [
        {
            "role": "system",
            "content": rag_system_prompt,
        }
    ]

    full_messages.extend(_bounded_history(history))

    full_messages.append({
        "role": "user",
        "content": user_message,
    })

    try:
        client = _get_client()

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=full_messages,
            temperature=settings.llm_temperature,
            max_tokens=min(settings.llm_max_tokens, 300),
        )

        reply = (
            response.choices[0].message.content
            or ""
        )

        reply = _strip_thinking(reply)

        # Check that the model replied in the required language
        if (
            reply
            and not response_matches_language(
                reply,
                language_profile,
            )
        ):
            try:
                reply = await _repair_language(
                    client=client,
                    original_user_message=user_message,
                    previous_reply=reply,
                    language_profile=language_profile,
                )

            except Exception as repair_error:
                print(
                    "[Language Repair Error]: "
                    f"{repair_error}"
                )

                # Preserve the English-only contract and use verified source facts
                # if a language-repair call cannot be completed.
                reply = build_grounded_fallback_reply(user_message, rag_context)

        if not reply:
            reply = build_grounded_fallback_reply(user_message, rag_context)

    except Exception as error:
        print(
            f"[LangGraph LLM Node Error]: {error}"
        )

        reply = build_grounded_fallback_reply(user_message, rag_context)

    return {
        "reply": reply
    }


# ============================================================
# NODE 5: SAVE CONVERSATION TO SUPABASE
# ============================================================

async def save_supabase_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
Save the current user/assistant turn to Supabase.

All messages belonging to the same session are stored
in the same conversation JSONB field.
"""

    user_id = state.get(
        "user_id",
        "",
    )

    session_id = state.get("session_id")
    user_message = state.get("message", "")
    assistant_reply = state.get("reply", "")

    try:
        await asyncio.to_thread(
            append_turn,
            user_id,
            session_id,
            user_message,
            assistant_reply,
        )

    except Exception as error:
        # Storage failure should not stop the chatbot response
        print(
            f"[Supabase Save Error]: {error}"
        )

    return {}
