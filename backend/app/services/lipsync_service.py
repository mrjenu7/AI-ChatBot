"""Map pronunciation to painted visemes inside the TTS provider's word intervals.

Word offsets are measured by the provider. Intra-word phone durations are
estimated (not a forced aligner). No random mouth animation or text-length clock.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# These names are a contract with frontend/src/components/avatar/atlas.js.
REST, AA, EE, OH, OO, FV, MBP, L, SZ, R = (
    "rest", "aa", "ee", "oh", "oo", "fv", "mbp", "l", "sz", "r"
)
PHONE_VISEMES = {
    "AA": AA, "AE": AA, "AH": AA, "AO": OH, "AW": AA, "AY": AA,
    "EH": EE, "ER": R, "EY": EE, "IH": EE, "IY": EE, "OW": OH,
    "OY": OH, "UH": OO, "UW": OO, "B": MBP, "P": MBP, "M": MBP,
    "F": FV, "V": FV, "L": L, "TH": L, "DH": L, "R": R,
    "W": OO, "Y": EE, "S": SZ, "Z": SZ, "SH": SZ, "ZH": SZ,
    "CH": SZ, "JH": SZ, "T": SZ, "D": SZ, "N": SZ,
    "K": AA, "G": AA, "NG": AA, "HH": AA,
}
WEIGHT = {REST: .7, AA: 1.4, EE: 1.3, OH: 1.4, OO: 1.3,
          FV: .8, MBP: .8, L: .8, SZ: .8, R: 1.0}


@lru_cache(maxsize=1)
def english_dictionary():
    try:
        import cmudict
        return cmudict.dict()
    except ImportError:
        return {}


def _indic_visemes(word: str) -> list[str]:
    """Gujarati and Devanagari share vowel/consonant offsets within their blocks.

    Respect matras, virama and conjuncts; do not insert an open vowel after a
    killed consonant. Final inherent schwa is suppressed as a useful heuristic.
    """
    result = []
    vowel = {0x05: AA, 0x06: AA, 0x07: EE, 0x08: EE, 0x09: OO,
             0x0A: OO, 0x0B: R, 0x0C: L, 0x0D: EE, 0x0F: EE,
             0x10: EE, 0x11: OH, 0x13: OH, 0x14: OH}
    matra = {0x3E: AA, 0x3F: EE, 0x40: EE, 0x41: OO, 0x42: OO,
             0x43: R, 0x44: R, 0x45: EE, 0x47: EE, 0x48: EE,
             0x49: OH, 0x4B: OH, 0x4C: OH}
    offsets = [(ord(c) - (0x0A80 if '\u0a80' <= c <= '\u0aff' else 0x0900))
               for c in word if '\u0900' <= c <= '\u097f' or '\u0a80' <= c <= '\u0aff']
    for i, cp in enumerate(offsets):
        if cp in vowel:
            result.append(vowel[cp])
        elif cp in matra:
            result.append(matra[cp])
        elif 0x15 <= cp <= 0x39:
            if cp in {0x2A, 0x2B, 0x2C, 0x2D, 0x2E}: shape = MBP
            elif cp == 0x35: shape = FV
            elif cp in {0x32, 0x33, 0x34}: shape = L
            elif cp in {0x30, 0x31}: shape = R
            elif cp == 0x2F: shape = EE
            elif cp <= 0x19 or cp == 0x39: shape = AA
            else: shape = SZ
            result.append(shape)
            # Include schwa only inside a word with no explicit vowel/virama.
            nxt = offsets[i + 1] if i + 1 < len(offsets) else None
            if nxt is not None and nxt not in matra and nxt not in {0x4D, 0x3C}:
                result.append(AA)
        elif cp in {0x01, 0x02}:  # nasalisation, not a new open vowel
            if not result: result.append(MBP)
    return result


@lru_cache(maxsize=4096)
def word_visemes(word: str, language: str = "en") -> tuple[list[str], str]:
    if re.search(r"[\u0900-\u097f\u0a80-\u0aff]", word):
        # Preserve English code-switching even if a provider groups scripts.
        pieces = re.findall(r"[\u0900-\u097f\u0a80-\u0aff]+|[A-Za-z']+", word)
        shapes = []
        for piece in pieces:
            shapes.extend(_indic_visemes(piece) if ord(piece[0]) > 127
                          else word_visemes(piece, "en")[0])
        return shapes, "indic-graphemes"
    value = ''.join(c for c in unicodedata.normalize('NFKD', word.lower())
                    if not unicodedata.combining(c)).strip(".,!?;:\"()[]")
    # Dictionary only for English. Applying English pronunciation to French or
    # Romanised Hindi/Gujarati would silently give the wrong mouth shapes.
    if language.split('-')[0] == "en":
        phones = english_dictionary().get(value)
        if phones:
            shapes = []
            for phone in phones[0]:
                p = re.sub(r"\d", "", phone)
                shapes.append(PHONE_VISEMES.get(p, AA))
                if p in {"AY", "EY", "OY"}: shapes.append(EE)
                elif p in {"AW", "OW"}: shapes.append(OO)
            return shapes, "english-dictionary"
    # Conservative Latin-script approximation for names and romanised input.
    if re.search(r"[a-z]", value):
        shapes = []
        for token in re.findall(r"ee|ea|oo|ou|ow|sh|ch|th|ph|[a-z]", value):
            if token in {"m", "b", "p"}: shape = MBP
            elif token in {"f", "v", "ph"}: shape = FV
            elif token in {"u", "w", "oo", "ou"}: shape = OO
            elif token in {"o", "ow"}: shape = OH
            elif token in {"e", "i", "y", "ee", "ea"}: shape = EE
            elif token in {"s", "z", "t", "d", "n", "j", "sh", "ch"}: shape = SZ
            elif token in {"l", "th"}: shape = L
            elif token == "r": shape = R
            else: shape = AA
            shapes.append(shape)
        return shapes, "latin-graphemes"
    # Unsupported writing systems use the live acoustic fallback in the browser.
    return [], "acoustic"


def build_viseme_cues(words: list[dict], language: str) -> tuple[list[dict], str]:
    cues, methods = [], set()
    previous_end = 0.0
    for word in sorted(words, key=lambda w: w["start"]):
        start = max(0.0, previous_end, float(word["start"]))
        end = max(start, float(word["end"]))
        if end <= start:
            continue
        shapes, method = word_visemes(str(word["text"]), language)
        methods.add(method)
        if not shapes:
            continue
        weights = [WEIGHT[s] for s in shapes]
        total, cursor = sum(weights), start
        for index, (shape, weight) in enumerate(zip(shapes, weights)):
            next_time = end if index == len(shapes) - 1 else cursor + (end-start)*weight/total
            cues.append({"start": round(cursor, 5), "end": round(next_time, 5), "viseme": shape})
            cursor = next_time
        previous_end = end
    return cues, "+".join(sorted(methods)) or "acoustic"
