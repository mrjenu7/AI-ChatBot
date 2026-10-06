import asyncio
import json
import re
from typing import AsyncIterator, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.graph.workflow import chat_graph
from app.services.supabase_service import append_turn, load_conversation, get_lead_by_session, upsert_lead
from app.services.language_service import (
    detect_language_profile,
    language_contract,
    localized_connection_error,
)
from app.services.company_guard import classify_scope, refusal, clarification
from app.services.llm_service import _get_client
from app.services.rag_service import retrieve_relevant_context


router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    language: str
    locale: str


def _clean_message(request: ChatRequest) -> tuple[str, str, str]:
    if not request.message or not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty",
        )

    user_id = (request.user_id or "").strip()
    session_id = (request.session_id or "").strip()

    # Create a user ID only when no user ID was provided.
    if not user_id:
        user_id = str(uuid4())
    else:
        try:
            user_id = str(UUID(user_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="user_id must be a valid UUID",
            )

    # Create a session ID only when no session ID was provided.
    if not session_id:
        session_id = str(uuid4())
    else:
        try:
            session_id = str(UUID(session_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="session_id must be a valid UUID",
            )

    return request.message.strip(), user_id, session_id


def _stream_system_prompt(rag_context: str, language_profile: Dict[str, object], strict: bool = False) -> str:
    contract = language_contract(language_profile)
    strict_prefix = ""
    if strict:
        strict_prefix = (
            "CRITICAL OUTPUT RULE: Start the very first sentence in English and keep "
            "every explanatory sentence strictly in English. Do not reply in any other language.\n"
        )

    return (
        f"{settings.system_prompt}\n\n"
        f"{strict_prefix}"
        "=== CURRENT RESPONSE LANGUAGE CONTRACT ===\n"
        f"{contract}\n"
        "Understand the user's message in whatever language they use. Always generate the answer "
        "ONLY in English. Do not reply in any non-English language.\n"
        "==========================================\n\n"
        "=== VERIFIED WE3VISION COMPANY KNOWLEDGE BASE ===\n"
        f"{rag_context}\n"
        "=================================================\n"
        "BUSINESS AGENT RULES:\n"
        "1. STRICT COMPANY FOCUS: You are exclusively the official AI Business Assistant of We3vision Private Limited. "
        "Answer ONLY questions related to We3vision (services, technologies, portfolio, projects, company background, "
        "office locations, careers, and contact info) or polite greetings/pleasantries.\n"
        "2. STRICT OUT-OF-SCOPE REFUSAL: If the user asks about ANY topic unrelated to We3vision "
        "(such as general knowledge, history, celebrities, sports, politics, weather, recipes, personal advice, "
        "general math, non-company coding tutorials, or other businesses), DO NOT ANSWER OR PROVIDE THAT INFORMATION. "
        "Politely decline the request in English, explaining that you can only answer questions "
        "about We3vision and its services. Invite them to ask about We3vision or provide contact details: "
        "info@we3vision.com / +91 7383216096.\n"
        "3. Use only approved facts from the knowledge base for company-specific claims.\n"
        "4. Never invent prices, policies, project commitments, vacancies, or undisclosed company facts.\n"
        "5. If a requested We3vision company fact is unavailable, say that in English and offer "
        "info@we3vision.com and +91 7383216096.\n"
        "6. Keep normal answers concise and conversational.\n"
        "7. Write speech-friendly sentences with natural punctuation so the voice can begin while the rest of "
        "the answer is still being generated.\n"
        f"8. FINAL CHECK: The answer must be 100% in English: {contract}\n"
    )


async def _history_messages(user_id: str, session_id: str) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    try:
        turns = await asyncio.to_thread(load_conversation, user_id, session_id)
    except Exception as error:
        print(f"[Supabase Load Error]: {error}")
        turns = []

    for turn in turns:
        history.append({"role": "user", "content": turn.get("user", "")})
        history.append({"role": "assistant", "content": turn.get("assistant", "")})
    # Keep the request compact for lower first-token latency.
    return history[-12:]


def _prefix_language_is_valid(text: str, profile: Dict[str, object] | None = None) -> bool:
    """Validate that streamed text does not contain non-English scripts."""
    gujarati_chars = sum(1 for ch in text if 0x0A80 <= ord(ch) <= 0x0AFF)
    devanagari_chars = sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)
    arabic_chars = sum(1 for ch in text if 0x0600 <= ord(ch) <= 0x06FF)
    cyrillic_chars = sum(1 for ch in text if 0x0400 <= ord(ch) <= 0x04FF)
    cjk_chars = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF or 0x3040 <= ord(ch) <= 0x30FF or 0xAC00 <= ord(ch) <= 0xD7AF)

    return (gujarati_chars + devanagari_chars + arabic_chars + cyrillic_chars + cjk_chars) < 2


async def _openai_text_stream(messages: List[Dict[str, str]]) -> AsyncIterator[str]:
    client = _get_client()
    stream = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _validated_text_stream(
    base_messages: List[Dict[str, str]],
    language_profile: Dict[str, object],
) -> AsyncIterator[str]:
    """Stream with a tiny prefix buffer, retrying once if non-English script is detected."""
    for attempt in range(2):
        messages = [dict(item) for item in base_messages]
        if attempt == 1:
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"]
                + "\nCRITICAL RETRY: Your previous attempt began in a non-English language. Begin immediately in English. The response MUST be in English only.",
            }

        prefix = ""
        released = False
        failed_language = False

        async for delta in _openai_text_stream(messages):
            # Do not expose hidden-thinking tags if a compatible model emits them.
            if not released:
                prefix += delta
                visible_probe = re.sub(r"<think>.*?</think>", "", prefix, flags=re.DOTALL).strip()

                if not _prefix_language_is_valid(visible_probe, language_profile):
                    failed_language = True
                    break

                if len(visible_probe) >= 20 or (" " in visible_probe and len(visible_probe) >= 8):
                    released = True
                    if prefix:
                        yield prefix
                    prefix = ""
                    continue
            else:
                yield delta

        if failed_language:
            continue

        if not released and prefix:
            # Short answers may complete before the probe reaches the threshold.
            if _prefix_language_is_valid(prefix, language_profile):
                yield prefix
                return
            if attempt == 0:
                continue

        return


async def _generate_dynamic_suggestions(
    user_message: str,
    assistant_reply: str,
    history: List[Dict[str, str]],
    lead: Optional[Dict] = None,
) -> List[str]:

    
    """
    
    Generate 2-3 relevant follow-up questions when the user
    shows interest in We3vision services or starting a project.
    """

    message_lower = user_message.lower()

    # Check recent conversation as well as the current message.
    conversation_text = " ".join(
        str(item.get("content", ""))
        for item in history[-8:]
    ).lower()

    project_keywords = [
        "project",
        "build",
        "develop",
        "development",
        "app",
        "application",
        "website",
        "software",
        "platform",
        "system",
        "solution",
        "ecommerce",
        "e-commerce",
        "ai",
        "chatbot",
        "idea",
    ]

    service_keywords = [
        "service",
        "services",
        "hire",
        "work with",
        "interested",
        "looking for",
        "need your",
    ]

    is_project_interest = any(
        keyword in message_lower
        for keyword in project_keywords
    )

    is_service_interest = any(
        keyword in message_lower
        for keyword in service_keywords
    )

    # Also continue suggestions if the conversation already contains
    # a project/service discussion.
    conversation_is_project = any(
        keyword in conversation_text
        for keyword in project_keywords
    )

    conversation_is_service = any(
        keyword in conversation_text
        for keyword in service_keywords
    )

    if not (
        is_project_interest
        or is_service_interest
        or conversation_is_project
        or conversation_is_service
    ):
        return []

    if not settings.has_openai_api_key:
        return []

    lead_context = ""

    if lead:
        lead_context = f"""
    CURRENT LEAD INFORMATION:

    Name: {lead.get("name") or "Not provided"}
    Email: {lead.get("email") or "Not provided"}
    Phone: {lead.get("phone") or "Not provided"}
    Company: {lead.get("company") or "Not provided"}
    Inquiry type: {lead.get("inquiry_type") or "Not determined"}
    Requirement: {lead.get("requirement") or "Not provided"}

    Use this information to make the suggestions more relevant.
    Do NOT ask for information that the user has already provided.
    """
    else:
        lead_context = """
    CURRENT LEAD INFORMATION:

    No lead information has been collected yet.

    Do not assume any name, email, phone, company, inquiry type,
    or requirement has been provided.
    """

    prompt = f"""
You are a follow-up suggestion generator for the We3vision AI Business Assistant.

The user has just sent a message to the chatbot.

Your job is to generate 3 clickable follow-up questions that the USER
would naturally want to ask the chatbot next.

IMPORTANT:
The suggestions must continue the user's current conversation.
They must NOT be generic business discovery questions.

User message:
{user_message}

Assistant response:
{assistant_reply}

{lead_context}

lead_context = ""

if lead:
    lead_context = 
CURRENT LEAD INFORMATION:

Name: {lead.get("name") or "Not provided"}
Email: {lead.get("email") or "Not provided"}
Phone: {lead.get("phone") or "Not provided"}
Company: {lead.get("company") or "Not provided"}
Inquiry type: {lead.get("inquiry_type") or "Not determined"}
Requirement: {lead.get("requirement") or "Not provided"}

Use this information to make the suggestions more relevant.
Do NOT ask for information that the user has already provided.



Generate 3 questions that:

1. Are directly related to what the user just asked.
2. Help the user continue the conversation with the chatbot.
3. Are questions the USER can ask We3vision.
4. Are useful for understanding the project or getting relevant guidance.
5. Do not repeat information already provided by the user.
6. Do not ask the user for information unless it is naturally useful.
7. Must be short and natural.
8. Must be suitable for clickable chatbot buttons.
9. Do not answer the questions.
10. Return ONLY a valid JSON array.
11. If the user's name, email, phone, company, inquiry type, or requirement
    is already known, NEVER ask for that information again.

12. If the project requirement is clear, suggestions should focus on:
    features, technology, process, timeline, cost discussion, or getting started.

13. If important lead information is missing and asking for it would naturally
    help the project, one suggestion may ask for it.

14. Suggestions must feel like the next logical step in THIS conversation.

Examples:

User:
"I have a clothing business and want to build an e-commerce website."

Good suggestions:
[
  "What features would you recommend for my fashion e-commerce website?",
  "What technology stack would you suggest for this project?",
  "What information do you need from me to get started?"
]

User:
"I want to build an AI chatbot for my company."

Good suggestions:
[
  "What type of AI chatbot would be suitable for my business?",
  "What features can you include in the chatbot?",
  "How can we get started with this project?"
]

User:
"Tell me about your AI development services."

Good suggestions:
[
  "What types of AI solutions do you build?",
  "Can you suggest an AI solution for my business?",
  "How can I start an AI project with We3vision?"
]

Return ONLY:
["Question 1", "Question 2", "Question 3"]
"""

    try:
        client = _get_client()

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate concise business discovery "
                        "questions for a chatbot."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""

        content = re.sub(
            r"```(?:json)?|```",
            "",
            content,
        ).strip()

        print("[Raw Suggestions Response]:", repr(content))

        try:
            suggestions = json.loads(content)

        except json.JSONDecodeError as error:
            print(f"[Suggestion Parse Error]: {error}")

            # Try to find a complete JSON array inside the response
            match = re.search(r"\[[\s\S]*\]", content)

            if match:
                try:
                    suggestions = json.loads(match.group(0))
                except json.JSONDecodeError:
                    print("[Suggestion Parse Error]: Extracted array is invalid")
                    return []
            else:
                print("[Suggestion Parse Error]: No complete JSON array found")

                # The model may have returned a truncated array.
                # Recover quoted strings that were successfully generated.
                partial_items = re.findall(r'"([^"]+)"', content)

                if not partial_items:
                    return []

                suggestions = partial_items

        if not isinstance(suggestions, list):
            print("[Suggestion Parse Error]: Suggestions is not a list")
            return []

        # Keep only short string questions.
        suggestions = [
            str(item).strip()
            for item in suggestions
            if isinstance(item, str) and item.strip()
        ]

        return suggestions[:3]

    except Exception as error:
        print(f"[Suggestion Generation Error]: {error}")
        return []


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    clean_message, user_id, session_id = _clean_message(request)
    language = detect_language_profile(clean_message)

    initial_state = {
        "user_id": user_id,
        "session_id": session_id,
        "message": clean_message,
        "history": [],
        "rag_context": "",
        "language": language,
        "reply": "",
    }

    final_state = await chat_graph.ainvoke(initial_state)

    return ChatResponse(
        reply=final_state.get("reply", ""),
        session_id=session_id,
        language="en",
        locale="en-IN",
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Low-latency NDJSON chat stream used by the real-time text + speech frontend."""
    clean_message, user_id, session_id = _clean_message(request)

    print("========== CHAT IDS ==========")
    print("USER ID:", user_id)
    print("SESSION ID:", session_id)
    print("MESSAGE:", clean_message)
    print("==============================")
    language = detect_language_profile(clean_message)

    async def event_stream() -> AsyncIterator[str]:
        code = "en"
        locale = "en-IN"
        yield json.dumps(
            {"type": "meta", "language": code, "locale": locale, "session_id": session_id},
            ensure_ascii=False,
        ) + "\n"

        history = await _history_messages(user_id, session_id)
        scope = await classify_scope(clean_message, history)
        if scope in {"OUT_OF_SCOPE", "AMBIGUOUS"}:
            guarded_reply = refusal(language) if scope == "OUT_OF_SCOPE" else clarification(language)
            try:
                await asyncio.to_thread(append_turn, user_id, session_id, clean_message, guarded_reply)
            except Exception as error:
                print(f"[Supabase Save Error]: {error}")
            yield json.dumps({"type": "delta", "text": guarded_reply}, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "done", "reply": guarded_reply, "language": code,
                "locale": locale, "session_id": session_id,
            }, ensure_ascii=False) + "\n"
            return

        if not settings.has_openai_api_key:
            fallback = localized_connection_error(language)
            try:
                await asyncio.to_thread(
                    append_turn, user_id, session_id, clean_message, fallback
                )
            except Exception as error:
                print(f"[Supabase Save Error]: {error}")
            yield json.dumps({"type": "delta", "text": fallback}, ensure_ascii=False) + "\n"
            yield json.dumps(
                {
                    "type": "done",
                    "reply": fallback,
                    "language": code,
                    "locale": locale,
                    "session_id": session_id,
                },
                ensure_ascii=False,
            ) + "\n"
            return

        rag_context = await asyncio.to_thread(retrieve_relevant_context, clean_message)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": _stream_system_prompt(rag_context, language)}
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": clean_message})

        full_reply_parts: List[str] = []
        try:
            async for delta in _validated_text_stream(messages, language):
                full_reply_parts.append(delta)
                yield json.dumps({"type": "delta", "text": delta}, ensure_ascii=False) + "\n"

            full_reply = "".join(full_reply_parts).strip()

            lead = None
            suggestions = []

            if not full_reply:
                # A rare provider/streaming incompatibility:
                # use the normal graph once and stream its reply in slices.
                initial_state = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": clean_message,
                    "history": [],
                    "rag_context": "",
                    "language": language,
                    "reply": "",
                }

                final_state = await chat_graph.ainvoke(initial_state)

                full_reply = str(
                    final_state.get("reply")
                    or localized_connection_error(language)
                ).strip()

                # Stream the fallback response in small chunks so the frontend
                # receives the answer progressively.
                for start in range(0, len(full_reply), 48):
                    piece = full_reply[start:start + 48]

                    yield json.dumps(
                        {
                            "type": "delta",
                            "text": piece,
                        },
                        ensure_ascii=False,
                    ) + "\n"

                # IMPORTANT:
                # Save the fallback response to Supabase too.
                try:
                    await asyncio.to_thread(
                        append_turn,
                        user_id,
                        session_id,
                        clean_message,
                        full_reply,
                    )
                except Exception as error:
                    print(f"[Supabase Save Error]: {error}")

            else:
                try:
                    await asyncio.to_thread(
                        append_turn,
                        user_id,
                        session_id,
                        clean_message,
                        full_reply,
                    )
                except Exception as error:
                    print(f"[Supabase Save Error]: {error}")


                # ============================================
                # EXTRACT + SAVE LEAD DATA
                # ============================================

                lead = await _update_chat_lead(
                    session_id=session_id,
                    user_message=clean_message,
                    history=history,
                )


                # ============================================
                # GENERATE DYNAMIC FOLLOW-UP SUGGESTIONS
                # ============================================

                suggestions = await _generate_dynamic_suggestions(
                    clean_message,
                    full_reply,
                    history,
                    lead,
                )
            print("===================================")
            print("USER:", clean_message)
            print("LEAD:", lead)
            print("SUGGESTIONS:", suggestions)
            print("===================================")


            yield json.dumps(
                {
                    "type": "done",
                    "reply": full_reply,
                    "language": code,
                    "locale": locale,
                    "session_id": session_id,
                    "suggestions": suggestions,
                },
                ensure_ascii=False,
            ) + "\n"
        except Exception as exc:
            print(f"[Streaming Chat Error]: {exc}")
            yield json.dumps({"type": "error", "message": "stream_failed"}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ============================================================
# LEAD EXTRACTION
# ============================================================

def _clean_lead_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


def _extract_lead_data(
    user_message: str,
    history: List[Dict[str, str]],
) -> Dict[str, Optional[str]]:
    """
    Extract basic lead information without another LLM call.

    This intentionally uses deterministic extraction so every chat
    message does NOT consume another LLM request/token budget.
    """

    text = str(user_message or "").strip()

    result = {
        "name": None,
        "email": None,
        "phone": None,
        "company": None,
        "inquiry_type": None,
        "requirement": None,
    }

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    email_match = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text,
        flags=re.IGNORECASE,
    )

    if email_match:
        result["email"] = email_match.group(0).strip()

    # --------------------------------------------------------
    # PHONE
    # --------------------------------------------------------

    phone_match = re.search(
        r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)",
        text,
    )

    if phone_match:
        phone = re.sub(r"[^\d+]", "", phone_match.group(0))

        # Avoid accidentally storing very short numbers.
        digits_only = re.sub(r"\D", "", phone)

        if 10 <= len(digits_only) <= 15:
            result["phone"] = phone

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name_patterns = [
        r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,60})",
        r"\bi am\s+([A-Za-z][A-Za-z .'-]{1,60})",
        r"\bi'm\s+([A-Za-z][A-Za-z .'-]{1,60})",
        r"\bthis is\s+([A-Za-z][A-Za-z .'-]{1,60})",
        r"\bname\s*:\s*([A-Za-z][A-Za-z .'-]{1,60})",
    ]

    for pattern in name_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            candidate = match.group(1).strip()

            # Stop common sentence continuations.
            candidate = re.split(
                r"\b(?:and|from|at|working|my|our|i|we)\b",
                candidate,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,.-")

            if 1 < len(candidate.split()) <= 5:
                result["name"] = candidate
                break

    # --------------------------------------------------------
    # COMPANY
    # --------------------------------------------------------

    company_patterns = [
    r"\bmy company name is\s+(.+?)(?:[.!?,]|$)",
    r"\bour company name is\s+(.+?)(?:[.!?,]|$)",
    r"\bthe company name is\s+(.+?)(?:[.!?,]|$)",
    r"\bcompany name is\s+(.+?)(?:[.!?,]|$)",

    r"\bmy company is\s+(.+?)(?:[.!?,]|$)",
    r"\bour company is\s+(.+?)(?:[.!?,]|$)",
    r"\bcompany is\s+(.+?)(?:[.!?,]|$)",

    r"\bwe are from\s+(.+?)(?:[.!?,]|$)",
    r"\bwe're from\s+(.+?)(?:[.!?,]|$)",
    r"\bi am from\s+(.+?)(?:[.!?,]|$)",
    r"\bi'm from\s+(.+?)(?:[.!?,]|$)",

    r"\bi work at\s+(.+?)(?:[.!?,]|$)",
    r"\bi work for\s+(.+?)(?:[.!?,]|$)",

    r"\bfrom\s+([A-Z][A-Za-z0-9& .'-]{1,80})(?:[.!?,]|$)",
]

    for pattern in company_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            candidate = match.group(1).strip()

            if candidate:
                result["company"] = candidate
                break

    # --------------------------------------------------------
    # INQUIRY TYPE
    # --------------------------------------------------------

    inquiry_patterns = [
        (
            r"\b(e[- ]?commerce|online store|online shop|"
            r"fashion website|shopping website)\b",
            "E-commerce website",
        ),
        (
            r"\b(ai|artificial intelligence|machine learning)\b",
            "AI development",
        ),
        (
            r"\b(chatbot|conversational ai|virtual assistant)\b",
            "AI chatbot",
        ),
        (
            r"\b(mobile app|android app|ios app|mobile application)\b",
            "Mobile application",
        ),
        (
            r"\b(website|web app|web application|web development)\b",
            "Website development",
        ),
        (
            r"\b(software|software development|custom software)\b",
            "Custom software development",
        ),
    ]

    for pattern, inquiry_type in inquiry_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            result["inquiry_type"] = inquiry_type
            break

    # --------------------------------------------------------
    # REQUIREMENT
    # --------------------------------------------------------

    requirement_keywords = [
        "need",
        "want",
        "looking for",
        "require",
        "requirement",
        "build",
        "develop",
        "development",
        "project",
        "website",
        "app",
        "application",
        "ecommerce",
        "e-commerce",
        "software",
        "platform",
        "solution",
        "chatbot",
        "ai",
    ]

    has_requirement = any(
        keyword in text.lower()
        for keyword in requirement_keywords
    )

    if has_requirement:
        # Store the user's actual requirement rather than
        # generating another LLM summary.
        result["requirement"] = text[:1000]

    return result

async def _update_chat_lead(
    session_id: str,
    user_message: str,
    history: List[Dict[str, str]],
) -> Optional[Dict]:
    """
    Extract lead information from the current user message and
    merge it into the existing session lead.
    """

    try:
        extracted = _extract_lead_data(
            user_message,
            history,
        )

        # Load current lead first.
        existing = await asyncio.to_thread(
            get_lead_by_session,
            session_id,
        )

        # If nothing useful was found and no lead exists,
        # don't create an empty lead.
        has_new_data = any(
            value
            for value in extracted.values()
        )

        if not existing and not has_new_data:
            return None

        # ----------------------------------------------------
        # Preserve previous requirement and append useful
        # requirement information when appropriate.
        # ----------------------------------------------------

        requirement = extracted.get("requirement")

        if (
            existing
            and existing.get("requirement")
            and requirement
            and requirement != existing.get("requirement")
        ):
            old_requirement = existing.get("requirement", "")

            # Avoid endlessly duplicating the same message.
            if requirement not in old_requirement:
                requirement = (
                    f"{old_requirement}\n{requirement}"
                )

        lead = await asyncio.to_thread(
            upsert_lead,
            session_id,
            extracted.get("name"),
            extracted.get("email"),
            extracted.get("phone"),
            extracted.get("company"),
            extracted.get("inquiry_type"),
            requirement,
            "new",
        )

        print("========== CHAT LEAD ==========")
        print("SESSION ID:", session_id)
        print("LEAD:", lead)
        print("===============================")

        return lead

    except Exception as error:
        # Lead storage should NEVER break the chatbot.
        print(f"[Lead Update Error]: {error}")
        return None