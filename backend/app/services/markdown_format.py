"""Repair LLM Markdown so the frontend (ReactMarkdown + GFM) can render it.

Some models (e.g. openai/gpt-oss on Groq) occasionally return Markdown
"flattened" onto one line:  "## Title ... ### Sub ... | A | B | |---|---| | x | y |"
Headings, list items and table rows must each start on their own line,
otherwise they are shown as raw characters (##, **, |).
"""
import re

FORMAT_RULES = (
    "FORMATTING: Reply in valid GitHub-flavoured Markdown with REAL line breaks. "
    "Put every heading (#, ##, ###) on its own line with a blank line before and after it. "
    "Put every bullet or numbered item on its own line. "
    "For tables, put the header row, the separator row (|---|---|) and every data row each on its own line, "
    "with a blank line before the table. "
    "Never place two headings, list items or table rows on the same line. "
    "Do not escape Markdown characters. Prefer bullet lists over tables unless a table is clearly better."
)


def normalize_markdown(text: str) -> str:
    if not text:
        return ""

    t = str(text).replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = t.replace("\\n", "\n")
    # \*\*bold\*\* -> **bold**
    t = re.sub(r"\\([\\`*_{}\[\]()#+.!>|~-])", r"\1", t)

    # --- 1. Tables flattened onto one line -------------------------------
    # separator row: "| |---|---| |" -> own line
    t = re.sub(r"\|\s*(\|?\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|)", r"|\n\1", t)
    # end of one row + start of next ("| |") -> new line
    t = re.sub(r"\|[ \t]+\|(?=[ \t]*[^\s|])", "|\n|", t)
    # text glued before a table header row -> blank line before the table
    t = re.sub(r"([^\n|])[ \t]*(\n?)(\|[^\n]*\|\n\|\s*:?-{3,})", r"\1\n\n\3", t)

    # --- 2. Headings in the middle of a line -------------------------------
    t = re.sub(r"(?<=\S)[ \t]+(#{1,6})[ \t]+(?=[A-Za-z0-9*])", r"\n\n\1 ", t)
    # a heading must be followed by a newline, not run into the paragraph
    # (only for "## Title Case Words" lines that are clearly too long)
    # --- 3. Inline bullets / numbered items --------------------------------
    t = re.sub(r"([.:!?])[ \t]+([-*•])[ \t]+(?=[A-Z*])", r"\1\n\2 ", t)
    t = re.sub(r"([.:!?])[ \t]+(\d{1,2}\.)[ \t]+(?=[A-Z*])", r"\1\n\2 ", t)

    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
