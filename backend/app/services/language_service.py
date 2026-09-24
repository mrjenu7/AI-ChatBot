"""Language detection and response-language enforcement utilities.

The business agent's language contract is driven by the *latest user message*.
Gujarati/Hindi script is detected deterministically.  Latin-script Gujlish and
Hinglish are handled with conversational indicators, and ``langid`` is used as
an optional broad-language fallback for other languages.
"""
from __future__ import annotations

import re
from typing import Any, Dict

try:  # Optional at import time; requirements.txt installs it for production.
    import langid  # type: ignore
except Exception:  # pragma: no cover - fallback keeps the app bootable
    langid = None


LANGUAGE_NAMES = {
    "en": "English",
    "gu": "Gujarati",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "ur": "Urdu",
    "bn": "Bengali",
    "pa": "Punjabi",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "ne": "Nepali",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "tr": "Turkish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
}

LOCALE_HINTS = {
    "en": "en-IN",
    "gu": "gu-IN",
    "hi": "hi-IN",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-BR",
    "nl": "nl-NL",
    "ru": "ru-RU",
    "uk": "uk-UA",
    "ar": "ar-SA",
    "ur": "ur-PK",
    "bn": "bn-IN",
    "pa": "pa-IN",
    "mr": "mr-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "ne": "ne-NP",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
    "tr": "tr-TR",
    "id": "id-ID",
    "vi": "vi-VN",
    "th": "th-TH",
}

# High-signal transliteration words.  Keep them conservative to avoid classifying
# normal English sentences as Indic transliteration.
GUJLISH_WORDS = {
    "kem", "cho", "tame", "tamari", "tamaru", "tamaro", "shu", "su",
    "chhe", "nathi", "mane", "ame", "amara", "aapo", "karsho", "karvu",
    "karo", "mate", "pachhi", "kyare", "kyaare", "maaf", "krupya",
}
HINGLISH_WORDS = {
    "aap", "kaise", "kya", "hai", "hain", "nahi", "nahin", "mujhe",
    "mera", "meri", "mere", "batao", "bataiye", "karna", "karo", "ka",
    "ki", "ke", "kripya", "abhi", "phir", "kab", "kyun",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def _script_count(text: str, start: int, end: int) -> int:
    return sum(1 for ch in text if start <= ord(ch) <= end)


def _latin_transliteration_code(text: str) -> str | None:
    words = _words(text)
    if not words:
        return None
    gu_score = sum(word in GUJLISH_WORDS for word in words)
    hi_score = sum(word in HINGLISH_WORDS for word in words)

    # Require multiple signals unless one phrase is unusually distinctive.
    lower = text.lower()
    if "kem cho" in lower or "shu chhe" in lower or "tame " in lower:
        gu_score += 2
    if "kaise ho" in lower or "kya hai" in lower or "mujhe " in lower:
        hi_score += 2

    if gu_score >= 2 and gu_score > hi_score:
        return "gu"
    if hi_score >= 2 and hi_score > gu_score:
        return "hi"
    return None


def detect_language_profile(text: str) -> Dict[str, Any]:
    """Return a serialisable language profile for the latest user message."""
    raw = (text or "").strip()
    if not raw:
        return {
            "code": "en",
            "name": "English",
            "style": "native",
            "locale": "en-IN",
            "source": "default",
        }

    # Native-script detection takes precedence over statistical detection.
    if _script_count(raw, 0x0A80, 0x0AFF) > 0:
        code, style, source = "gu", "native", "unicode-script"
    elif _script_count(raw, 0x0900, 0x097F) > 0:
        # Devanagari may also be Marathi/Nepali.  langid can refine this while
        # preserving Hindi as the practical default for this project's scope.
        code = "hi"
        if langid is not None:
            try:
                detected, _ = langid.classify(raw)
                if detected in {"hi", "mr", "ne"}:
                    code = detected
            except Exception:
                pass
        style, source = "native", "unicode-script"
    elif _script_count(raw, 0x0600, 0x06FF) > 0:
        code, style, source = "ar", "native", "unicode-script"
        if langid is not None:
            try:
                detected, _ = langid.classify(raw)
                if detected in {"ar", "ur", "fa"}:
                    code = detected
            except Exception:
                pass
    elif _script_count(raw, 0x0980, 0x09FF) > 0:
        code, style, source = "bn", "native", "unicode-script"
    elif _script_count(raw, 0x0A00, 0x0A7F) > 0:
        code, style, source = "pa", "native", "unicode-script"
    elif _script_count(raw, 0x0B80, 0x0BFF) > 0:
        code, style, source = "ta", "native", "unicode-script"
    elif _script_count(raw, 0x0C00, 0x0C7F) > 0:
        code, style, source = "te", "native", "unicode-script"
    elif _script_count(raw, 0x0C80, 0x0CFF) > 0:
        code, style, source = "kn", "native", "unicode-script"
    elif _script_count(raw, 0x0D00, 0x0D7F) > 0:
        code, style, source = "ml", "native", "unicode-script"
    elif _script_count(raw, 0x0400, 0x04FF) > 0:
        code, style, source = "ru", "native", "unicode-script"
        if langid is not None:
            try:
                detected, _ = langid.classify(raw)
                if detected in {"ru", "uk", "bg", "sr", "mk", "be"}:
                    code = detected
            except Exception:
                pass
    elif _script_count(raw, 0x3040, 0x30FF) > 0:
        code, style, source = "ja", "native", "unicode-script"
    elif _script_count(raw, 0xAC00, 0xD7AF) > 0:
        code, style, source = "ko", "native", "unicode-script"
    elif _script_count(raw, 0x4E00, 0x9FFF) > 0:
        code, style, source = "zh", "native", "unicode-script"
    else:
        translit = _latin_transliteration_code(raw)
        if translit:
            code, style, source = translit, "latin", "transliteration"
        else:
            code, style, source = "en", "native", "fallback"
            if langid is not None and len(raw) >= 4:
                try:
                    detected, confidence = langid.classify(raw)
                    # langid's score is log-like, not a 0..1 probability; use its
                    # best label but keep tiny/ambiguous Latin messages English.
                    if detected:
                        code = detected
                        source = "langid"
                except Exception:
                    pass

    return {
        "code": code,
        "name": LANGUAGE_NAMES.get(code, code.upper()),
        "style": style,
        "locale": LOCALE_HINTS.get(code, code),
        "source": source,
    }


def language_contract(profile: Dict[str, Any]) -> str:
    """Create a strict prompt instruction for the requested response language."""
    code = str(profile.get("code") or "en")
    style = str(profile.get("style") or "native")
    name = str(profile.get("name") or LANGUAGE_NAMES.get(code, code.upper()))

    if code == "gu" and style == "native":
        return (
            "Write the COMPLETE answer in natural, conversational Gujarati using Gujarati script. "
            "Do not answer in English or Hindi. English may appear only for unavoidable brand names, "
            "technical product names, email addresses, URLs, phone numbers, or code. Translate all "
            "normal explanatory sentences into Gujarati."
        )
    if code == "hi" and style == "native":
        return (
            "Write the COMPLETE answer in natural, conversational Hindi using Devanagari script. "
            "Do not answer in English or Gujarati. English may appear only for unavoidable brand names, "
            "technical product names, email addresses, URLs, phone numbers, or code. Translate all "
            "normal explanatory sentences into Hindi."
        )
    if code == "gu" and style == "latin":
        return (
            "Reply in Gujarati written in Latin letters (Gujlish), matching the user's transliterated style. "
            "Do not switch to Gujarati script and do not turn the answer into standard English."
        )
    if code == "hi" and style == "latin":
        return (
            "Reply in Hindi written in Latin letters (Hinglish), matching the user's transliterated style. "
            "Do not switch to Devanagari and do not turn the answer into standard English."
        )
    if code == "en":
        return "Write the complete answer in English only."

    return (
        f"Write the complete answer in {name}. The latest user message is in {name}; do not switch to English. "
        "Keep only unavoidable names, URLs, email addresses, phone numbers, code, and technical identifiers unchanged."
    )


def response_matches_language(reply: str, profile: Dict[str, Any]) -> bool:
    """Best-effort guard used before a response is returned to the frontend."""
    text = (reply or "").strip()
    if not text:
        return False

    code = str(profile.get("code") or "en")
    style = str(profile.get("style") or "native")

    if code == "gu" and style == "native":
        gu = _script_count(text, 0x0A80, 0x0AFF)
        devanagari = _script_count(text, 0x0900, 0x097F)
        latin = sum(ch.isascii() and ch.isalpha() for ch in text)
        # Gujarati must be the real explanatory language, not just a short greeting
        # wrapped around an otherwise English answer. Technical names may stay Latin.
        return gu >= 3 and gu > devanagari and (latin <= 12 or gu >= latin * 0.35)
    if code == "hi" and style == "native":
        dev = _script_count(text, 0x0900, 0x097F)
        gu = _script_count(text, 0x0A80, 0x0AFF)
        latin = sum(ch.isascii() and ch.isalpha() for ch in text)
        return dev >= 3 and dev > gu and (latin <= 12 or dev >= latin * 0.35)
    if code == "en":
        return _script_count(text, 0x0A80, 0x0AFF) == 0 and _script_count(text, 0x0900, 0x097F) == 0
    if code == "gu" and style == "latin":
        return _script_count(text, 0x0A80, 0x0AFF) == 0
    if code == "hi" and style == "latin":
        return _script_count(text, 0x0900, 0x097F) == 0

    if langid is not None and len(text) >= 20:
        try:
            detected, _ = langid.classify(text)
            return detected == code
        except Exception:
            pass
    return True


def localized_connection_error(profile: Dict[str, Any]) -> str:
    code = str(profile.get("code") or "en")
    style = str(profile.get("style") or "native")

    if code == "gu" and style == "native":
        return "માફ કરશો, હમણાં AI સેવામાં કનેક્શનની સમસ્યા છે. કૃપા કરીને થોડીવાર પછી ફરી પ્રયાસ કરો."
    if code == "hi" and style == "native":
        return "क्षमा करें, अभी AI सेवा से कनेक्शन में समस्या है। कृपया थोड़ी देर बाद फिर प्रयास करें।"
    if code == "gu" and style == "latin":
        return "Maaf karsho, hamna AI service sathe connection ma samasya chhe. Krupya thodi vaar pachhi fari prayas karo."
    if code == "hi" and style == "latin":
        return "Maaf kijiye, abhi AI service se connection mein samasya hai. Kripya thodi der baad phir koshish karein."
    return "Sorry, the AI service is temporarily unavailable. Please try again in a moment."
