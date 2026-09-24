"""Natural multilingual text-to-speech service for the website chatbot."""
from __future__ import annotations

import re
import asyncio
import base64
from typing import AsyncIterator, Dict, List, Optional

try:  # Installed via requirements.txt; guarded so backend can still boot safely.
    import edge_tts  # type: ignore
except Exception:  # pragma: no cover
    edge_tts = None

from app.services.language_service import detect_language_profile
from app.services.lipsync_service import build_viseme_cues


PREFERRED_VOICES: Dict[str, str] = {
    "gu": "gu-IN-DhwaniNeural",
    "hi": "hi-IN-SwaraNeural",
    "en": "en-IN-NeerjaNeural",
}

_VOICE_CACHE: Optional[List[dict]] = None


def clean_text_for_speech(text: str) -> str:
    """Remove display-only Markdown/table symbols before synthesis.

    Chat rendering is untouched; this function changes only the text passed to
    the speech engine. Table cell content is kept in reading order, while pipes
    and separator dash runs are never spoken.
    """
    spoken_lines: List[str] = []

    for original_line in str(text or "").splitlines():
        trimmed = original_line.strip()
        if not trimmed:
            continue

        normalized = trimmed.replace("¦", "|")
        table_body = normalized.removeprefix("|").removesuffix("|")
        table_cells = [cell.strip() for cell in table_body.split("|")]
        is_table_separator = (
            len(table_cells) > 1
            and all((not cell) or re.fullmatch(r":?-{3,}:?", cell) for cell in table_cells)
        )
        if is_table_separator or re.fullmatch(r":?-{3,}:?", trimmed):
            continue

        if "|" in normalized:
            content_cells = [
                cell for cell in table_cells
                if cell and not re.fullmatch(r":?-{2,}:?", cell)
            ]
            if content_cells:
                spoken_lines.append(". ".join(content_cells))
            continue

        spoken_lines.append(original_line)

    value = " ".join(spoken_lines).strip()
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"^\s*[-*•]\s*", "", value, flags=re.MULTILINE)

    # Defense in depth for direct /tts calls and streamed fragments. Keep
    # meaningful single hyphens inside words/paths, but remove table borders.
    value = re.sub(r"[|¦]", " ", value)
    value = re.sub(r":?-{2,}:?", " ", value)
    value = re.sub(r"(^|\s)[-–—]+(?=[\s.,;:]|$)", r"\1 ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


async def _voice_catalog() -> List[dict]:
    global _VOICE_CACHE
    if _VOICE_CACHE is not None:
        return _VOICE_CACHE
    if edge_tts is None:
        return []
    try:
        _VOICE_CACHE = await edge_tts.list_voices()
    except Exception:
        # A temporary outage must not poison all later voice lookups.
        return []
    return _VOICE_CACHE or []


async def choose_voice(language_code: str) -> str:
    code = (language_code or "en").lower().split("-")[0]
    preferred = PREFERRED_VOICES.get(code)
    if preferred:
        return preferred

    voices = await _voice_catalog()
    matches = [
        voice for voice in voices
        if str(voice.get("Locale", "")).lower().startswith(f"{code}-")
    ]
    if matches:
        female = next((v for v in matches if str(v.get("Gender", "")).lower() == "female"), None)
        selected = female or matches[0]
        return str(selected.get("ShortName"))

    raise ValueError(f"No speech voice is available for language '{code}'.")


def speech_rate(language_code: str) -> str:
    # Keep Indic speech clear while using a slightly more natural, quicker pace.
    return "-4%" if language_code in {"gu", "hi", "mr", "bn", "pa"} else "+0%"


async def stream_speech(text: str, language_code: str | None = None) -> AsyncIterator[bytes]:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    clean = clean_text_for_speech(text)
    if not clean:
        raise ValueError("Text cannot be empty")

    profile = detect_language_profile(clean)
    code = (language_code or profile["code"] or "en").lower().split("-")[0]
    voice = await choose_voice(code)

    communicate = edge_tts.Communicate(
        clean,
        voice=voice,
        rate=speech_rate(code),
        pitch="+0Hz",
        volume="+0%",
        boundary="WordBoundary",
    )
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            yield chunk["data"]


async def synthesize_speech_bundle(text: str, language_code: str | None = None) -> dict:
    """One synthesis call returns matching audio, word offsets and viseme cues.

    Never synthesize audio separately from the timings: two calls can have
    different pauses. No audio or transcripts are written to disk here.
    """
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed; install backend/requirements.txt")
    clean = clean_text_for_speech(text)
    if not clean:
        raise ValueError("Text cannot be empty after removing formatting")
    code = (language_code or detect_language_profile(clean)["code"] or "en").lower().split('-')[0]
    if code == "auto":
        code = detect_language_profile(clean)["code"]
    voice = await choose_voice(code)
    audio, words = bytearray(), []
    communicate = edge_tts.Communicate(
        clean, voice=voice, rate=speech_rate(code), pitch="+0Hz",
        volume="+0%", boundary="WordBoundary", connect_timeout=8, receive_timeout=25,
    )
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk.get("data", b""))
        elif chunk.get("type") == "WordBoundary":
            start = max(0, chunk["offset"]) / 10_000_000
            duration = max(0, chunk["duration"]) / 10_000_000
            words.append({"text": str(chunk["text"]), "start": start, "end": start + duration})
    if not audio:
        raise RuntimeError("The speech service returned no audio")
    # Dictionary loading/phonetic processing must not block other API requests.
    cues, method = await asyncio.to_thread(build_viseme_cues, words, code)
    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"), "mime_type": "audio/mpeg",
        "language": code, "voice": voice, "text": clean, "words": words, "visemes": cues,
        "timing_source": "provider-word-boundaries" if words else "audio-analysis",
        "phoneme_source": method,
        "phoneme_timing": "estimated-within-words" if cues else "acoustic",
    }
