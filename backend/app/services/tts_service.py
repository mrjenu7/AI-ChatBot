"""Natural multilingual text-to-speech service for the website chatbot."""
from __future__ import annotations

import re
import asyncio
import base64
import unicodedata
from typing import AsyncIterator, Dict, List, Optional, Tuple

try:  # Installed via requirements.txt; guarded so backend can still boot safely.
    import edge_tts  # type: ignore
except Exception:  # pragma: no cover
    edge_tts = None

from app.services.language_service import LOCALE_HINTS, detect_language_profile
from app.services.lipsync_service import build_viseme_cues


# Keep the same female speaker family used by the existing project for the
# three primary languages. Other languages are selected from the provider's
# native locale catalogue, preferring a female voice when one is available.
PREFERRED_VOICES: Dict[str, str] = {
    "gu": "gu-IN-DhwaniNeural",
    "gu-IN": "gu-IN-DhwaniNeural",
    "hi": "hi-IN-SwaraNeural",
    "hi-IN": "hi-IN-SwaraNeural",
    "en": "en-IN-NeerjaNeural",
    "en-IN": "en-IN-NeerjaNeural",
}

_VOICE_CACHE: Optional[List[dict]] = None

# Terms that are commonly misread when a native-language voice encounters a
# brand/technical token. These substitutions affect only the spoken copy; the
# text rendered in the chatbot remains byte-for-byte unchanged.
_SPOKEN_TERM_ALIASES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwe\s*[-_]?\s*3\s*[-_]?\s*vision\b", re.IGNORECASE), "We Three Vision"),
    (re.compile(r"\bwe3vision\b", re.IGNORECASE), "We Three Vision"),
    (re.compile(r"\bchat\s*gpt\b", re.IGNORECASE), "Chat G P T"),
    (re.compile(r"\bopen\s*ai\b", re.IGNORECASE), "Open A I"),
    (re.compile(r"\bfast\s*api\b", re.IGNORECASE), "Fast A P I"),
)

# Technical initialisms are intentionally conservative. Spelling these out is
# more reliable across Hindi/Gujarati/other native voices than asking each
# locale to guess an English acronym pronunciation.
_SPELLED_INITIALISMS = {
    "AI", "API", "AWS", "BGE", "CRM", "CSS", "CPU", "CSV", "DL", "ERP", "GCP",
    "GPT", "GPU", "HTML", "HTTP", "HTTPS", "IDE", "JSON", "JWT", "LLM", "ML",
    "NLP", "OCR", "PDF", "QR", "SDK", "STT", "TTS", "UI", "URL", "UX", "XML",
}

_SMALL_NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


_GUJARATI_LETTER_NAMES = {
    "A": "એ", "B": "બી", "C": "સી", "D": "ડી", "E": "ઈ", "F": "એફ",
    "G": "જી", "H": "એચ", "I": "આઈ", "J": "જે", "K": "કે", "L": "એલ",
    "M": "એમ", "N": "એન", "O": "ઓ", "P": "પી", "Q": "ક્યૂ", "R": "આર",
    "S": "એસ", "T": "ટી", "U": "યુ", "V": "વી", "W": "ડબલ્યુ", "X": "એક્સ",
    "Y": "વાય", "Z": "ઝેડ",
}

_GUJARATI_DIGIT_NAMES = {
    "0": "ઝીરો", "1": "વન", "2": "ટુ", "3": "થ્રી", "4": "ફોર",
    "5": "ફાઇવ", "6": "સિક્સ", "7": "સેવન", "8": "એઇટ", "9": "નાઇન",
}

# Speech-only Gujarati forms for names/terms that native Gujarati voices can
# otherwise read with inconsistent English phonetics. The visible chat message
# is never changed. Keep this list conservative and pronunciation-focused.
_GUJARATI_TERM_ALIASES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwe\s+three\s+vision\b", re.IGNORECASE), "વી થ્રી વિઝન"),
    (re.compile(r"\bchat\s+g\s+p\s+t\b", re.IGNORECASE), "ચેટ જી પી ટી"),
    (re.compile(r"\bopen\s+a\s+i\b", re.IGNORECASE), "ઓપન એ આઈ"),
    (re.compile(r"\bfast\s+a\s+p\s+i\b", re.IGNORECASE), "ફાસ્ટ એ પી આઈ"),
    (re.compile(r"\bgoogle\b", re.IGNORECASE), "ગૂગલ"),
    (re.compile(r"\bwhatsapp\b", re.IGNORECASE), "વોટ્સએપ"),
    (re.compile(r"\bpython\b", re.IGNORECASE), "પાયથન"),
    (re.compile(r"\bjavascript\b", re.IGNORECASE), "જાવાસ્ક્રિપ્ટ"),
    (re.compile(r"\breact\b", re.IGNORECASE), "રિએક્ટ"),
)


def _clean_speech_inline(value: str) -> str:
    """Remove display-only symbols without touching the text shown in chat."""
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(
        r"https?://(?:www\.)?([^\s/]+)(?:/[^\s]*)?",
        lambda m: m.group(1).replace(".", " "),
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\bwww\.([^\s/]+)(?:/[^\s]*)?",
        lambda m: m.group(1).replace(".", " "),
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b([A-Z0-9._%+\-]+)@([A-Z0-9.\-]+\.[A-Z]{2,})\b",
        lambda m: "{} {}".format(re.sub(r'[._+%-]+', ' ', m.group(1)), re.sub(r'[.-]+', ' ', m.group(2))),
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    value = re.sub(r"[|¦]", " ", value)
    value = re.sub(r":?-{2,}:?", " ", value)
    value = re.sub(r"[–—]+", ", ", value)
    value = re.sub(r"[\\/]+", ", ", value)
    value = re.sub(r"&+", ", ", value)
    value = re.sub(r"[()\[\]{}<>]", " ", value)
    value = re.sub(r"[#*_~^=+%@₹$€£¥©®™]", " ", value)
    value = re.sub(r'[“”"]', " ", value)
    value = re.sub(r"[•▪◦●◆◇■□►▶]+", " ", value)
    # Remove emoji/pictographic symbols while preserving letters from all scripts.
    value = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]", " ", value)
    value = re.sub(r"\s+([,.;:!?।！？])", r"\1", value)
    value = re.sub(r"([,;:]){2,}", r"\1", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _finish_speech_phrase(value: str) -> str:
    phrase = _clean_speech_inline(value)
    if not phrase:
        return ""
    if re.search(r"[.!?।！？]$", phrase):
        return phrase
    if re.search(r"[,;:]$", phrase):
        phrase = phrase[:-1].rstrip()
    return f"{phrase}."


def clean_text_for_speech(text: str) -> str:
    """Create a natural, punctuation-aware speech-only copy of chat text.

    The visible assistant response is never changed. Markdown/table formatting
    becomes spoken phrase boundaries, separator rows are discarded, and symbols
    that neural/browser TTS engines may literally announce are removed.
    """
    spoken_phrases: List[str] = []
    in_code_block = False

    for original_line in str(text or "").splitlines():
        trimmed = original_line.strip()
        if not trimmed:
            continue

        if trimmed.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        trimmed = re.sub(r"^#{1,6}\s*", "", trimmed)
        trimmed = re.sub(r"^>+\s*", "", trimmed)
        trimmed = re.sub(r"^\s*(?:[-*•▪◦]+|\d+[.)])\s+", "", trimmed).strip()
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
            for cell in table_cells:
                if not cell or re.fullmatch(r":?-{2,}:?", cell):
                    continue
                phrase = _finish_speech_phrase(cell)
                if phrase:
                    spoken_phrases.append(phrase)
            continue

        phrase = _finish_speech_phrase(trimmed)
        if phrase:
            spoken_phrases.append(phrase)

    return re.sub(r"\s+", " ", " ".join(spoken_phrases)).strip()


def _number_words(value: str) -> str:
    """English reading for digits embedded inside a Latin brand/identifier."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return " ".join(_SMALL_NUMBER_WORDS[int(ch)] for ch in value if ch.isdigit())
    if number in _SMALL_NUMBER_WORDS:
        return _SMALL_NUMBER_WORDS[number]
    if 20 < number < 100:
        tens, ones = divmod(number, 10)
        return _TENS[tens * 10] if not ones else f"{_TENS[tens * 10]} {_SMALL_NUMBER_WORDS[ones]}"
    # Model/version identifiers such as 2024 or 125 are clearer digit-by-digit
    # than a locale-dependent number reading inside an English technical token.
    return " ".join(_SMALL_NUMBER_WORDS[int(ch)] for ch in value)


def _spoken_identifier(token: str) -> str:
    """Turn mixed letter/number identifiers into locale-stable speech tokens."""
    value = token.replace("_", " ").replace("-", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", value)
    value = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", value)
    parts = [part for part in re.split(r"\s+", value) if part]
    spoken: List[str] = []
    for part in parts:
        if part.isdigit():
            spoken.append(_number_words(part))
        elif part.upper() in _SPELLED_INITIALISMS:
            spoken.append(" ".join(part.upper()))
        else:
            spoken.append(part)
    return " ".join(spoken)


def _gujarati_initialism(token: str) -> str:
    """Gujarati-script letter names keep acronyms clear in the Gujarati voice."""
    return " ".join(_GUJARATI_LETTER_NAMES.get(ch, ch) for ch in token.upper())


def _gujarati_identifier(token: str) -> str:
    """Gujarati speech form for mixed technical identifiers such as GPT4/n8n."""
    value = token.replace("_", " ").replace("-", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", value)
    value = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", value)
    parts = [part for part in re.split(r"\s+", value) if part]
    spoken: List[str] = []
    for part in parts:
        if part.isdigit():
            spoken.append(" ".join(_GUJARATI_DIGIT_NAMES.get(ch, ch) for ch in part))
        elif part.upper() in _SPELLED_INITIALISMS or (len(part) <= 3 and part.isalpha() and part.upper() == part):
            spoken.append(_gujarati_initialism(part))
        else:
            spoken.append(part)
    return " ".join(spoken)


def _stabilize_gujarati_text(value: str) -> str:
    """Normalize Gujarati Unicode/spacing so combining marks reach TTS intact."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\u00a0", " ").replace("\ufeff", "").replace("\u200b", "")
    # ZWJ/ZWNJ are useful for typography but can cause inconsistent TTS tokenization.
    value = value.replace("\u200c", "").replace("\u200d", "")
    value = re.sub(r"\s+([,.;:!?।！？])", r"\1", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_pronunciation_for_speech(text: str, language_code: str | None = None) -> str:
    """Normalize brands/technical tokens for reliable multilingual pronunciation.

    The transformation is speech-only. Gujarati gets an extra native-script
    pass so its neural voice does not guess English letter/digit pronunciation
    and is less likely to merge or omit syllables around mixed-script terms.
    """
    code = str(language_code or "").lower().split("-")[0]
    value = str(text or "")
    if code == "gu":
        value = _stabilize_gujarati_text(value)

    for pattern, replacement in _SPOKEN_TERM_ALIASES:
        value = pattern.sub(replacement, value)

    # Initialisms that occur as standalone tokens.
    def spell_initialism(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.upper() not in _SPELLED_INITIALISMS:
            return token
        return _gujarati_initialism(token) if code == "gu" else " ".join(token.upper())

    value = re.sub(r"\b[A-Za-z]{2,6}\b", spell_initialism, value)

    # Letter+digit brand/model tokens: We3Vision, GPT4, B2B, n8n, HTML5, etc.
    mixed_identifier = re.compile(
        r"(?<![\w])(?:[A-Za-z][A-Za-z0-9._+\-]*\d[A-Za-z0-9._+\-]*|\d+[A-Za-z][A-Za-z0-9._+\-]*)(?![\w])"
    )
    value = mixed_identifier.sub(
        (lambda m: _gujarati_identifier(m.group(0))) if code == "gu" else (lambda m: _spoken_identifier(m.group(0))),
        value,
    )

    if code == "gu":
        for pattern, replacement in _GUJARATI_TERM_ALIASES:
            value = pattern.sub(replacement, value)
        value = _stabilize_gujarati_text(value)
    else:
        value = re.sub(r"\s+([,.;:!?।！？])", r"\1", value)
        value = re.sub(r"\s+", " ", value).strip()
    return value


def _normalise_locale(language_code: str | None) -> tuple[str, str]:
    raw = str(language_code or "").strip().replace("_", "-")
    if not raw or raw.lower() == "auto":
        return "", ""
    pieces = raw.split("-")
    code = pieces[0].lower()
    if len(pieces) >= 2 and pieces[1]:
        locale = f"{code}-{pieces[1].upper()}"
    else:
        locale = str(LOCALE_HINTS.get(code, code))
    return code, locale


def _range_count(text: str, start: int, end: int) -> int:
    return sum(1 for ch in text if start <= ord(ch) <= end)


def _strong_script_language(text: str, requested_code: str, detected_code: str) -> str | None:
    """Find a dominant native script so the voice accent follows the actual text."""
    groups = {
        "gu": _range_count(text, 0x0A80, 0x0AFF),
        "dev": _range_count(text, 0x0900, 0x097F),
        "bn": _range_count(text, 0x0980, 0x09FF),
        "pa": _range_count(text, 0x0A00, 0x0A7F),
        "ta": _range_count(text, 0x0B80, 0x0BFF),
        "te": _range_count(text, 0x0C00, 0x0C7F),
        "kn": _range_count(text, 0x0C80, 0x0CFF),
        "ml": _range_count(text, 0x0D00, 0x0D7F),
        "arabic": _range_count(text, 0x0600, 0x06FF),
        "cyr": _range_count(text, 0x0400, 0x04FF),
        "ja": _range_count(text, 0x3040, 0x30FF),
        "ko": _range_count(text, 0xAC00, 0xD7AF),
        "zh": _range_count(text, 0x4E00, 0x9FFF),
    }
    group, count = max(groups.items(), key=lambda item: item[1])
    if count <= 0:
        return None

    # Same-script languages need the requested/detected locale to refine them.
    if group == "dev":
        if requested_code in {"hi", "mr", "ne"}:
            return requested_code
        return detected_code if detected_code in {"hi", "mr", "ne"} else "hi"
    if group == "arabic":
        if requested_code in {"ar", "ur", "fa"}:
            return requested_code
        return detected_code if detected_code in {"ar", "ur", "fa"} else "ar"
    if group == "cyr":
        if requested_code in {"ru", "uk", "bg", "sr", "mk", "be"}:
            return requested_code
        return detected_code if detected_code in {"ru", "uk", "bg", "sr", "mk", "be"} else "ru"
    # Japanese commonly contains Han characters as well; any kana is a strong
    # signal that the intended spoken language is Japanese.
    if groups["ja"] > 0:
        return "ja"
    return group


def resolve_speech_language(text: str, requested_language: str | None = None) -> tuple[str, str]:
    """Resolve code+locale using actual script first, requested locale second.

    This prevents a Hindi/Gujarati sentence from being spoken with an English
    voice when stale frontend metadata is present, while still trusting the
    requested locale for Latin-script languages such as French/Spanish.
    """
    profile = detect_language_profile(text)
    detected_code = str(profile.get("code") or "en").lower().split("-")[0]
    requested_code, requested_locale = _normalise_locale(requested_language)
    strong = _strong_script_language(text, requested_code, detected_code)
    if strong:
        return strong, str(LOCALE_HINTS.get(strong, profile.get("locale") or strong))
    if requested_code:
        return requested_code, requested_locale or str(LOCALE_HINTS.get(requested_code, requested_code))
    return detected_code, str(profile.get("locale") or LOCALE_HINTS.get(detected_code, detected_code))


def prepare_text_for_tts(text: str, requested_language: str | None = None) -> tuple[str, str, str]:
    clean = clean_text_for_speech(text)
    if not clean:
        raise ValueError("Text cannot be empty after removing formatting")
    code, locale = resolve_speech_language(clean, requested_language)
    spoken = normalize_pronunciation_for_speech(clean, code)
    if not spoken:
        raise ValueError("Text cannot be empty after pronunciation normalization")
    return spoken, code, locale


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
    code, locale = _normalise_locale(language_code)
    code = code or "en"
    locale = locale or str(LOCALE_HINTS.get(code, code))

    preferred = PREFERRED_VOICES.get(locale) or PREFERRED_VOICES.get(code)
    if preferred:
        return preferred

    voices = await _voice_catalog()
    exact_matches = [
        voice for voice in voices
        if str(voice.get("Locale", "")).lower() == locale.lower()
    ]
    matches = exact_matches or [
        voice for voice in voices
        if str(voice.get("Locale", "")).lower().startswith(f"{code}-")
    ]
    if matches:
        female = next((v for v in matches if str(v.get("Gender", "")).lower() == "female"), None)
        selected = female or matches[0]
        return str(selected.get("ShortName"))

    raise ValueError(f"No speech voice is available for language '{locale}'.")


def speech_rate(language_code: str) -> str:
    # Keep language-native rhythm without changing the user's working pause
    # timings. Indic/Arabic/CJK languages get a little more room than English.
    code = (language_code or "en").lower().split("-")[0]
    if code == "gu":
        # Gujarati benefits from a touch more articulation without changing the
        # user's already-approved inter-sentence pause timings.
        return "-11%"
    if code in {"hi", "mr", "bn", "pa", "ta", "te", "kn", "ml", "ne", "ur"}:
        return "-9%"
    if code in {"ar", "ja", "ko", "zh", "ru", "uk"}:
        return "-7%"
    return "-6%"


async def stream_speech(text: str, language_code: str | None = None) -> AsyncIterator[bytes]:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    spoken, code, locale = prepare_text_for_tts(text, language_code)
    voice = await choose_voice(locale)

    communicate = edge_tts.Communicate(
        spoken,
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

    spoken, code, locale = prepare_text_for_tts(text, language_code)
    voice = await choose_voice(locale)
    audio, words = bytearray(), []
    communicate = edge_tts.Communicate(
        spoken, voice=voice, rate=speech_rate(code), pitch="+0Hz",
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
        "language": code, "locale": locale, "voice": voice, "text": spoken, "words": words, "visemes": cues,
        "timing_source": "provider-word-boundaries" if words else "audio-analysis",
        "phoneme_source": method,
        "phoneme_timing": "estimated-within-words" if cues else "acoustic",
    }
