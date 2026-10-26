"""Repair LLM Markdown so the frontend (ReactMarkdown + GFM) can render it.

Some models (e.g. openai/gpt-oss on Groq) occasionally return Markdown
"flattened" onto one line:  "## Title ... ### Sub ... | A | B | |---|---| | x | y |"
Headings, list items and table rows must each start on their own line,
otherwise they are shown as raw characters (##, **, |).
"""
import re

FORMAT_RULES = (
    "FORMATTING RULES (Clean Markdown like ChatGPT):\n"
    "- Output clear, standard GitHub-flavoured Markdown with REAL line breaks.\n"
    "- Put every heading (## or ###) on its own line with an empty line before and after it.\n"
    "- Never place paragraph text or list items on the same line as a heading.\n"
    "- Put each bullet item on its own line starting with '- '.\n"
    "- Separate paragraphs with an empty blank line.\n"
    "- Never run sentences or items together on a single line.\n"
    "- Do not escape markdown syntax characters (do not output \\# or \\*\\*).\n"
    "- Prefer bullet lists over tables unless a table is clearly better."
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

    # --- 2. Glued horizontal dividers ------------------------------------
    t = re.sub(r"(?<=\S)[ \t]+(---+)[ \t]*", r"\n\n\1\n\n", t)
    t = re.sub(r"^[ \t]*(---+)[ \t]+(?=\S)", r"\1\n\n", t, flags=re.MULTILINE)

    # --- 3. Headings in the middle of a line -------------------------------
    t = re.sub(r"(?<=\S)[ \t]+(#{1,6}[ \t]+)", r"\n\n\1", t)

    # --- 4. Heading followed directly by a bullet on the same line ---------
    # e.g. "#### 1. Design & Creative – 6 Services - Brand Identity..."
    t = re.sub(
        r"^(#{1,6}[ \t]+[^\n]+?)[ \t]+[-*\u2022][ \t]+(?=[A-Za-z0-9*])",
        r"\1\n\n- ",
        t,
        flags=re.MULTILINE,
    )

    # --- 5. Heading ending with ? or : followed by body text ---------------
    t = re.sub(
        r"^(#{1,6}[ \t]+[^\n?:]+?[?:])[ \t]+([A-Z])",
        r"\1\n\n\2",
        t,
        flags=re.MULTILINE,
    )

    # --- 6. Heading title followed directly by body sentence on same line ---
    # e.g. "## What We3vision Does We3vision Private Limited..."
    t = re.sub(
        r"^(#{1,6}[ \t]+(?:Overview of What [A-Za-z0-9]+ Does|About [A-Za-z0-9]+|Introduction to [A-Za-z0-9]+|What [A-Za-z0-9]+ Does))[ \t]+([A-Z])",
        r"\1\n\n\2",
        t,
        flags=re.MULTILINE,
    )
    t = re.sub(
        r"^(#{1,6}[ \t]+[A-Z][A-Za-z0-9\s/&,\u2013\u2014'-]+?\b(?:Does|About|Services|Solutions|Overview|Guide|Locations|Details|Catalogue|Catalog|Snapshot|Summary|FAQ))\s+([A-Z])",
        r"\1\n\n\2",
        t,
        flags=re.MULTILINE,
    )

    # --- 7. Un-squash glued sentences -------------------------------------
    t = re.sub(r"([a-z0-9][.:!?])([A-Z])", r"\1\n\n\2", t)

    # --- 8. Ensure blank line after every heading line --------------------
    t = re.sub(r"^(#{1,6}[ \t]+[^\n]+)\n(?!\n|#{1,6}[ \t])", r"\1\n\n", t, flags=re.MULTILINE)

    # --- 9. Convert unicode bullets (•, etc.) to markdown dash ------------
    t = re.sub(r"[ \t]*[\u2022\u25cf\u25aa][ \t]*", "\n- ", t)

    # --- 10. Inline bullets / numbered items ------------------------------
    # After colon: "with: - **Branding..." -> "with:\n\n- **Branding..."
    t = re.sub(r"([.:!?])[ \t]+[-*][ \t]+(?=\*\*|[A-Za-z0-9])", r"\1\n\n- ", t)
    # After closing paren or slug: "(/brand-identity) - Graphics..." -> "(/brand-identity)\n- Graphics..."
    t = re.sub(r"(\(\/[a-z0-9_-]+\))[ \t]+[-*][ \t]+(?=\*\*|[A-Za-z0-9])", r"\1\n- ", t, flags=re.IGNORECASE)
    # After bullet item ending in period or paren:
    t = re.sub(r"([a-z0-9\)])\.[ \t]+[-*][ \t]+(?=\*\*|[A-Za-z0-9])", r"\1.\n- ", t)
    # Any other inline bullet between items:
    t = re.sub(r"(?<=[^\n])[ \t]+[-*][ \t]+(?=\*\*[A-Z]|[A-Z][a-z]+)", r"\n- ", t)

    # Numbered items inline: "1. Foo 2. Bar" -> "1. Foo\n2. Bar"
    t = re.sub(r"([.:!?])[ \t]+(\d{1,2}\.)[ \t]+(?=[A-Z*])", r"\1\n\2 ", t)

    # --- 11. Ensure blank line before list starts -------------------------
    t = re.sub(r"([^\n#\-*\u2022\d)])\n([-*\u2022][ \t]+|\d{1,2}\.[ \t]+)", r"\1\n\n\2", t)

    # --- 12. Collapse double newlines between consecutive list items ------
    t = re.sub(r"(\n[-*\u2022][ \t]+[^\n]+)\n\n(?=[-*\u2022][ \t])", r"\1\n", t)
    t = re.sub(r"(\n[-*\u2022][ \t]+[^\n]+)\n\n(?=[-*\u2022][ \t])", r"\1\n", t)
    t = re.sub(r"(\n\d{1,2}\.[ \t]+[^\n]+)\n\n(?=\d{1,2}\.[ \t])", r"\1\n", t)
    t = re.sub(r"(\n\d{1,2}\.[ \t]+[^\n]+)\n\n(?=\d{1,2}\.[ \t])", r"\1\n", t)

    # --- 13. Ensure blank line after list blocks --------------------------
    t = re.sub(r"(\n[-*\u2022][ \t]+[^\n]+)\n([A-Z*])", r"\1\n\n\2", t)

    # --- 14. Clean trailing spaces and excessive newlines -----------------
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
