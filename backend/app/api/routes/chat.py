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
from app.services.supabase_service import (
    append_turn,
    load_conversation,
    get_lead_by_session,
    upsert_lead,
)
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
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    user_id = (request.user_id or "").strip()
    session_id = (request.session_id or "").strip()

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


def _clean_chat_response(text: str) -> str:
    """Remove Markdown formatting from chatbot responses."""
    if not text:
        return ""

    text = str(text)

    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!_)_(?!\s)(.*?)(?<!\s)_", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _stream_system_prompt(
    rag_context: str,
    language_profile: Dict[str, object],
    strict: bool = False,
) -> str:
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
        "8. RESPONSE FORMAT: Return plain text only. Do not use Markdown formatting. "
        "Never use #, ##, ###, *, **, _, backticks, Markdown bullets, numbered Markdown lists, "
        "Markdown tables, table pipes (|), or other Markdown syntax. "
        "Use short natural paragraphs separated by line breaks.\n"
        f"9. FINAL CHECK: The answer must be 100% in English and plain text: {contract}\n"
    )


async def _history_messages(
    user_id: str,
    session_id: str,
) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []

    try:
        turns = await asyncio.to_thread(
            load_conversation,
            user_id,
            session_id,
        )
    except Exception as error:
        print(f"[Supabase Load Error]: {error}")
        turns = []

    for turn in turns:
        history.append({"role": "user", "content": turn.get("user", "")})
        history.append({"role": "assistant", "content": turn.get("assistant", "")})

    return history[-12:]


def _prefix_language_is_valid(
    text: str,
    profile: Dict[str, object] | None = None,
) -> bool:
    """Validate that streamed text does not contain non-English scripts."""
    gujarati_chars = sum(1 for ch in text if 0x0A80 <= ord(ch) <= 0x0AFF)
    devanagari_chars = sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)
    arabic_chars = sum(1 for ch in text if 0x0600 <= ord(ch) <= 0x06FF)
    cyrillic_chars = sum(1 for ch in text if 0x0400 <= ord(ch) <= 0x04FF)
    cjk_chars = sum(
        1
        for ch in text
        if (
            0x4E00 <= ord(ch) <= 0x9FFF
            or 0x3040 <= ord(ch) <= 0x30FF
            or 0xAC00 <= ord(ch) <= 0xD7AF
        )
    )

    return (
        gujarati_chars
        + devanagari_chars
        + arabic_chars
        + cyrillic_chars
        + cjk_chars
    ) < 2


async def _openai_text_stream(
    messages: List[Dict[str, str]],
) -> AsyncIterator[str]:
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
                + "\nCRITICAL RETRY: Your previous attempt began in a non-English language. "
                "Begin immediately in English. The response MUST be in English only.",
            }

        prefix = ""
        released = False
        failed_language = False

        async for delta in _openai_text_stream(messages):
            if not released:
                prefix += delta

                visible_probe = re.sub(
                    r"<think>.*?</think>",
                    "",
                    prefix,
                    flags=re.DOTALL,
                ).strip()

                if not _prefix_language_is_valid(
                    visible_probe,
                    language_profile,
                ):
                    failed_language = True
                    break

                if len(visible_probe) >= 20 or (
                    " " in visible_probe and len(visible_probe) >= 8
                ):
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
            if _prefix_language_is_valid(prefix, language_profile):
                yield prefix
                return

            if attempt == 0:
                continue

        return


def _fallback_suggestions(
    user_message: str,
    assistant_reply: str,
    lead: Optional[Dict] = None,
) -> List[str]:
    """
    Deterministic fallback suggestions.

    These are intentionally local/no-LLM so suggestions still appear
    even if the suggestion LLM returns invalid/empty JSON.
    """
    text = f"{user_message} {assistant_reply}".lower()

    if any(
        keyword in text
        for keyword in [
            "ai development",
            "artificial intelligence",
            "machine learning",
            "ai solution",
        ]
    ):
        return [
            "What types of AI solutions do you build?",
            "Can you suggest an AI solution for my business?",
            "How can I start an AI project with We3vision?",
        ]

    if any(
        keyword in text
        for keyword in [
            "chatbot",
            "conversational ai",
            "virtual assistant",
        ]
    ):
        return [
            "What features can you include in the chatbot?",
            "What technology would you recommend for the chatbot?",
            "How can I get started with this project?",
        ]

    if any(
        keyword in text
        for keyword in [
            "e-commerce",
            "ecommerce",
            "online store",
            "online shop",
        ]
    ):
        return [
            "What features would you recommend for my e-commerce website?",
            "What technology stack would you suggest for this project?",
            "How can I get started with the project?",
        ]

    if any(
        keyword in text
        for keyword in [
            "mobile app",
            "android app",
            "ios app",
            "mobile application",
        ]
    ):
        return [
            "What features can you include in a mobile app?",
            "What technology stack would you recommend?",
            "How can I get started with the app?",
        ]

    if any(
        keyword in text
        for keyword in [
            "website",
            "web app",
            "web application",
            "web development",
        ]
    ):
        return [
            "What features would you recommend for my website?",
            "What technology stack would you suggest?",
            "How can I get started with the project?",
        ]

    if any(
        keyword in text
        for keyword in [
            "service",
            "services",
            "what do you",
            "what does we3vision",
        ]
    ):
        return [
            "What types of AI solutions do you build?",
            "Can you suggest a solution for my business?",
            "How can I start a project with We3vision?",
        ]

    return [
        "What solutions can We3vision provide for my business?",
        "What technologies does We3vision work with?",
        "How can I get started with We3vision?",
    ]


async def _generate_dynamic_suggestions(
    user_message: str,
    assistant_reply: str,
    history: List[Dict[str, str]],
    lead: Optional[Dict] = None,
) -> List[str]:
    """
    Generate 3 relevant follow-up questions.

    The LLM is used when available, but a deterministic fallback guarantees
    that the frontend receives suggestions instead of [] when the LLM returns
    invalid JSON, an empty response, or a transient error.
    """

    fallback = _fallback_suggestions(
        user_message,
        assistant_reply,
        lead,
    )

    if not settings.has_openai_api_key:
        return fallback

    lead_context = """
CURRENT LEAD INFORMATION:

No lead information has been collected yet.

Do not assume any name, email, phone, company, inquiry type,
or requirement has been provided.
"""

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

    prompt = f"""
You are a follow-up suggestion generator for the We3vision AI Business Assistant.

Generate exactly 3 short clickable questions that the user would naturally ask next.

The questions must continue THIS conversation and must be directly relevant
to the latest user message and assistant answer.

USER MESSAGE:
{user_message}

ASSISTANT RESPONSE:
{assistant_reply}

{lead_context}

RULES:
1. Return exactly 3 questions.
2. Questions must be about We3vision and its services/projects.
3. Do not answer the questions.
4. Do not repeat information already provided.
5. Do not ask for name, email, phone, company, inquiry type, or requirement
   if that information is already known.
6. If the requirement is clear, focus on features, technology, process,
   timeline, cost discussion, or getting started.
7. Keep each question short and natural.
8. Return ONLY a valid JSON array of strings.
9. No Markdown and no code fences.

Example:
["What types of AI solutions do you build?",
 "Can you suggest an AI solution for my business?",
 "How can I start an AI project with We3vision?"]
"""

    try:
        client = _get_client()

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate exactly 3 concise follow-up questions. "
                        "Return only valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=150,
        )

        content = (
            response.choices[0].message.content or ""
        ).strip()

        content = re.sub(
            r"```(?:json)?|```",
            "",
            content,
        ).strip()

        print("[Raw Suggestions Response]:", repr(content))

        suggestions: List[str] = []

        try:
            parsed = json.loads(content)

            if isinstance(parsed, list):
                suggestions = [
                    str(item).strip()
                    for item in parsed
                    if isinstance(item, str) and item.strip()
                ]
        except json.JSONDecodeError as error:
            print(f"[Suggestion Parse Error]: {error}")

            match = re.search(r"\[[\s\S]*?\]", content)

            if match:
                try:
                    parsed = json.loads(match.group(0))

                    if isinstance(parsed, list):
                        suggestions = [
                            str(item).strip()
                            for item in parsed
                            if isinstance(item, str) and item.strip()
                        ]
                except json.JSONDecodeError as inner_error:
                    print(
                        "[Suggestion Parse Error]: "
                        f"Extracted array is invalid: {inner_error}"
                    )

            if not suggestions:
                # Recover complete quoted strings if possible.
                partial_items = re.findall(
                    r'"([^"]{8,200})"',
                    content,
                )

                suggestions = [
                    item.strip()
                    for item in partial_items
                    if item.strip()
                ]

        # Never let malformed model output disable the feature.
        if len(suggestions) < 3:
            print(
                "[Suggestion Fallback]: "
                f"LLM returned {len(suggestions)} usable suggestions"
            )

            merged: List[str] = []

            for item in suggestions + fallback:
                item = str(item).strip()

                if item and item not in merged:
                    merged.append(item)

                if len(merged) == 3:
                    break

            suggestions = merged

        return suggestions[:3]

    except Exception as error:
        print(f"[Suggestion Generation Error]: {error}")
        print("[Suggestion Fallback]: Using deterministic suggestions")
        return fallback[:3]


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

        yield (
            json.dumps(
                {
                    "type": "meta",
                    "language": code,
                    "locale": locale,
                    "session_id": session_id,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        history = await _history_messages(user_id, session_id)

        scope = await classify_scope(
            clean_message,
            history,
        )

        if scope in {"OUT_OF_SCOPE", "AMBIGUOUS"}:
            guarded_reply = (
                refusal(language)
                if scope == "OUT_OF_SCOPE"
                else clarification(language)
            )

            try:
                await asyncio.to_thread(
                    append_turn,
                    user_id,
                    session_id,
                    clean_message,
                    guarded_reply,
                )
            except Exception as error:
                print(f"[Supabase Save Error]: {error}")

            yield (
                json.dumps(
                    {
                        "type": "delta",
                        "text": guarded_reply,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            suggestions = _fallback_suggestions(
                clean_message,
                guarded_reply,
                None,
            )

            yield (
                json.dumps(
                    {
                        "type": "done",
                        "reply": guarded_reply,
                        "language": code,
                        "locale": locale,
                        "session_id": session_id,
                        "suggestions": suggestions,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            return

        if not settings.has_openai_api_key:
            fallback = localized_connection_error(language)

            try:
                await asyncio.to_thread(
                    append_turn,
                    user_id,
                    session_id,
                    clean_message,
                    fallback,
                )
            except Exception as error:
                print(f"[Supabase Save Error]: {error}")

            yield (
                json.dumps(
                    {
                        "type": "delta",
                        "text": fallback,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            yield (
                json.dumps(
                    {
                        "type": "done",
                        "reply": fallback,
                        "language": code,
                        "locale": locale,
                        "session_id": session_id,
                        "suggestions": _fallback_suggestions(
                            clean_message,
                            fallback,
                        ),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            return

        rag_context = await asyncio.to_thread(
            retrieve_relevant_context,
            clean_message,
        )

        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": _stream_system_prompt(
                    rag_context,
                    language,
                ),
            }
        ]

        messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": clean_message,
            }
        )

        full_reply_parts: List[str] = []

        try:
            async for delta in _validated_text_stream(
                messages,
                language,
            ):
                full_reply_parts.append(delta)

                yield (
                    json.dumps(
                        {
                            "type": "delta",
                            "text": delta,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            full_reply = "".join(full_reply_parts).strip()
            full_reply = _clean_chat_response(full_reply)

            lead = None
            suggestions: List[str] = []

            if not full_reply:
                # Rare provider/streaming incompatibility.
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

                for start in range(0, len(full_reply), 48):
                    piece = full_reply[start:start + 48]

                    yield (
                        json.dumps(
                            {
                                "type": "delta",
                                "text": piece,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

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

                suggestions = _fallback_suggestions(
                    clean_message,
                    full_reply,
                )

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

                # Lead extraction is deterministic and does not use an LLM.
                lead = await _update_chat_lead(
                    session_id=session_id,
                    user_message=clean_message,
                    history=history,
                )

                # Generate suggestions. The function always has a deterministic
                # fallback, so the feature cannot silently become [] because
                # of malformed LLM JSON.
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

            yield (
                json.dumps(
                    {
                        "type": "done",
                        "reply": full_reply,
                        "language": code,
                        "locale": locale,
                        "session_id": session_id,
                        "suggestions": suggestions[:3],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        except Exception as exc:
            import traceback

            print(f"[Streaming Chat Error]: {exc}")
            traceback.print_exc()

            yield (
                json.dumps(
                    {
                        "type": "error",
                        "message": "stream_failed",
                        "detail": str(exc),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

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

    Deterministic extraction keeps every normal chat message from
    consuming another LLM request.
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

    # EMAIL
    email_match = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text,
        flags=re.IGNORECASE,
    )

    if email_match:
        result["email"] = email_match.group(0).strip()

    # PHONE
    phone_match = re.search(
        r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)",
        text,
    )

    if phone_match:
        phone = re.sub(
            r"[^\d+]",
            "",
            phone_match.group(0),
        )

        digits_only = re.sub(
            r"\D",
            "",
            phone,
        )

        if 10 <= len(digits_only) <= 15:
            result["phone"] = phone

    # NAME
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

            candidate = re.split(
                r"\b(?:and|from|at|working|my|our|i|we)\b",
                candidate,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,.-")

            if 1 < len(candidate.split()) <= 5:
                result["name"] = candidate
                break

    # COMPANY
    #
    # Important: do NOT use a generic "from <anything>" pattern here.
    # That pattern was capable of treating normal phrases such as
    # "your portfolio for this use case..." as company information.
    company_patterns = [
        r"\bmy company name is\s+(.+?)(?:[.!?,]|$)",
        r"\bour company name is\s+(.+?)(?:[.!?,]|$)",
        r"\bthe company name is\s+(.+?)(?:[.!?,]|$)",
        r"\bcompany name is\s+(.+?)(?:[.!?,]|$)",
        r"\bmy company is\s+(.+?)(?:[.!?,]|$)",
        r"\bour company is\s+(.+?)(?:[.!?,]|$)",
        r"\bcompany is\s+(.+?)(?:[.!?,]|$)",
        r"\bi work at\s+(.+?)(?:[.!?,]|$)",
        r"\bi work for\s+(.+?)(?:[.!?,]|$)",
        r"\bwe are from\s+(.+?)(?:[.!?,]|$)",
        r"\bwe're from\s+(.+?)(?:[.!?,]|$)",
    ]

    for pattern in company_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            candidate = match.group(1).strip()

            # Avoid storing obvious conversational filler.
            candidate = re.sub(
                r"\s+",
                " ",
                candidate,
            ).strip(" ,.-")

            if (
                candidate
                and len(candidate) <= 100
                and candidate.lower()
                not in {
                    "you",
                    "your",
                    "we3vision",
                    "this",
                    "that",
                }
            ):
                result["company"] = candidate
                break

    # INQUIRY TYPE
    inquiry_patterns = [
        (
            r"\b(e[- ]?commerce|online store|online shop|"
            r"fashion website|shopping website)\b",
            "E-commerce website",
        ),
        (
            r"\b(chatbot|conversational ai|virtual assistant)\b",
            "AI chatbot",
        ),
        (
            r"\b(ai|artificial intelligence|machine learning)\b",
            "AI development",
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
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            result["inquiry_type"] = inquiry_type
            break

    # REQUIREMENT
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
        "service",
        "services",
    ]

    has_requirement = any(
        keyword in text.lower()
        for keyword in requirement_keywords
    )

    if has_requirement:
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

        existing = await asyncio.to_thread(
            get_lead_by_session,
            session_id,
        )

        has_new_data = any(
            value
            for value in extracted.values()
        )

        if not existing and not has_new_data:
            return None

        requirement = extracted.get("requirement")

        if (
            existing
            and existing.get("requirement")
            and requirement
            and requirement != existing.get("requirement")
        ):
            old_requirement = existing.get(
                "requirement",
                "",
            )

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
        # Lead storage must never break the chatbot.
        print(f"[Lead Update Error]: {error}")
        return None
