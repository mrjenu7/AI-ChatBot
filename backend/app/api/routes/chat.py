import asyncio
import json
import re
from typing import AsyncIterator, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.graph.workflow import chat_graph
from app.services.google_sheets_storage import append_turn, load_today_chat
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
    user_id: Optional[str] = "guest_user"
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    language: str
    locale: str


def _clean_message(request: ChatRequest) -> tuple[str, str, str]:
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    user_id = (request.user_id or "guest_user").strip() or "guest_user"
    session_id = (request.session_id or "").strip() or uuid4().hex
    return request.message.strip(), user_id, session_id


def _stream_system_prompt(rag_context: str, language_profile: Dict[str, object], strict: bool = False) -> str:
    contract = language_contract(language_profile)
    strict_prefix = ""
    if strict:
        strict_prefix = (
            "CRITICAL OUTPUT RULE: Start the very first sentence in the required language/script and keep "
            "every explanatory sentence in that language. Do not begin with an English preface.\n"
        )

    return (
        f"{settings.system_prompt}\n\n"
        f"{strict_prefix}"
        "=== CURRENT RESPONSE LANGUAGE CONTRACT ===\n"
        f"{contract}\n"
        "The language is determined ONLY from the latest user message. Do not copy the language of older "
        "chat turns. If the knowledge-base text is English, translate its facts into the required response "
        "language.\n"
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
        "Politely decline the request in the REQUIRED response language, explaining that you can only answer questions "
        "about We3vision and its services. Invite them to ask about We3vision or provide contact details: "
        "info@we3vision.com / +91 7383216096.\n"
        "3. Use only approved facts from the knowledge base for company-specific claims.\n"
        "4. Never invent prices, policies, project commitments, vacancies, or undisclosed company facts.\n"
        "5. If a requested We3vision company fact is unavailable, say that in the REQUIRED response language and offer "
        "info@we3vision.com and +91 7383216096.\n"
        "6. Keep normal answers concise and conversational.\n"
        "7. Write speech-friendly sentences with natural punctuation so the voice can begin while the rest of "
        "the answer is still being generated.\n"
        f"8. FINAL CHECK: {contract}\n"
    )


async def _history_messages(user_id: str, session_id: str) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    try:
        turns = await asyncio.to_thread(load_today_chat, user_id, session_id)
    except Exception as error:
        print(f"[Google Sheets Load Error]: {error}")
        turns = []

    for turn in turns:
        history.append({"role": "user", "content": turn.get("user", "")})
        history.append({"role": "assistant", "content": turn.get("assistant", "")})
    # Keep the request compact for lower first-token latency.
    return history[-12:]


def _prefix_language_is_valid(text: str, profile: Dict[str, object]) -> bool:
    """Validate only native Gujarati/Hindi prefixes before exposing streamed text.

    This small gate prevents an accidental English answer from being displayed/spoken while preserving
    low latency. Other languages rely on the strong prompt contract.
    """
    code = str(profile.get("code") or "en")
    style = str(profile.get("style") or "native")
    if style != "native" or code not in {"gu", "hi"}:
        return True

    if code == "gu":
        script_chars = sum(1 for ch in text if 0x0A80 <= ord(ch) <= 0x0AFF)
        wrong_script = sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)
    else:
        script_chars = sum(1 for ch in text if 0x0900 <= ord(ch) <= 0x097F)
        wrong_script = sum(1 for ch in text if 0x0A80 <= ord(ch) <= 0x0AFF)

    return script_chars >= 3 and script_chars > wrong_script


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
    """Stream with a tiny prefix buffer, retrying once if Gujarati/Hindi script is wrong."""
    for attempt in range(2):
        messages = [dict(item) for item in base_messages]
        if attempt == 1:
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"]
                + "\nCRITICAL RETRY: Your previous attempt began in the wrong language. Begin immediately in the required language/script.",
            }

        prefix = ""
        released = False
        failed_language = False

        async for delta in _openai_text_stream(messages):
            # Do not expose hidden-thinking tags if a compatible model emits them.
            if not released:
                prefix += delta
                visible_probe = re.sub(r"<think>.*?</think>", "", prefix, flags=re.DOTALL).strip()

                if _prefix_language_is_valid(visible_probe, language_profile):
                    released = True
                    if prefix:
                        yield prefix
                    prefix = ""
                    continue

                # Native Gujarati/Hindi should reveal its script quickly. If it does not,
                # discard this attempt before the wrong-language text reaches the UI/TTS.
                if len(visible_probe) >= 140:
                    failed_language = True
                    break
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
    final_language = final_state.get("language") or language

    return ChatResponse(
        reply=final_state.get("reply", ""),
        session_id=session_id,
        language=str(final_language.get("code", "en")),
        locale=str(final_language.get("locale", "en-IN")),
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Low-latency NDJSON chat stream used by the real-time text + speech frontend."""
    clean_message, user_id, session_id = _clean_message(request)
    language = detect_language_profile(clean_message)

    async def event_stream() -> AsyncIterator[str]:
        code = str(language.get("code", "en"))
        locale = str(language.get("locale", "en-IN"))
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
                print(f"[Google Sheets Save Error]: {error}")
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
                print(f"[Google Sheets Save Error]: {error}")
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
            if not full_reply:
                # A rare provider/streaming incompatibility: use the normal graph once, then
                # stream its already-generated reply in small slices so the frontend still works.
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
                full_reply = str(final_state.get("reply") or localized_connection_error(language)).strip()
                for start in range(0, len(full_reply), 48):
                    piece = full_reply[start:start + 48]
                    yield json.dumps({"type": "delta", "text": piece}, ensure_ascii=False) + "\n"
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
                    print(f"[Google Sheets Save Error]: {error}")

            yield json.dumps(
                {
                    "type": "done",
                    "reply": full_reply,
                    "language": code,
                    "locale": locale,
                    "session_id": session_id,
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
