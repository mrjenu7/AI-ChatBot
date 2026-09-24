import json
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

from app.core.config import settings


SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LEGACY_HEADERS = [
    "user_id",
    "date",
    "time",
    "conversation_json",
]

HEADERS = [
    "user_id",
    "session_id",
    "date",
    "time",
    "conversation_json",
]

_STORAGE_LOCK = RLock()


def _backend_directory() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _credentials_path() -> Path:
    path = Path(settings.google_service_account_file)

    if not path.is_absolute():
        path = _backend_directory() / path

    if not path.exists():
        raise FileNotFoundError(
            f"Google service-account file was not found: {path}"
        )

    return path


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.app_timezone))


def _normalize_message_text(value: str) -> str:
    """
    Preserve the original language, paragraphs, numbered lists,
    bullet points, email addresses, and phone numbers.
    """
    text = unicodedata.normalize("NFC", str(value or "")).strip()

    # Remove Markdown bold and inline-code markers only.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.*?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # Normalize line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize bullet symbols.
    text = re.sub(
        r"(?m)^[ \t]*[*•][ \t]+",
        "- ",
        text,
    )

    # Remove unnecessary spaces around line breaks.
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)

    # Keep at most one blank line between paragraphs.
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normalize horizontal spacing only.
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def _conversation_to_display(
    conversation: List[Dict[str, str]],
) -> str:
    """
    Convert a conversation into a human-readable Google Sheets cell.
    """
    sections: List[str] = []

    for turn in conversation:
        if not isinstance(turn, dict):
            continue

        user_text = _normalize_message_text(
            turn.get("user", "")
        )
        assistant_text = _normalize_message_text(
            turn.get("assistant", "")
        )

        sections.append(
            f"USER:\n{user_text}\n\n"
            f"ASSISTANT:\n{assistant_text}"
        )

    return "\n\n────────────────────────\n\n".join(sections)


def _parse_display_conversation(
    value: str,
) -> List[Dict[str, str]]:
    """
    Read conversations stored in the human-readable format.
    """
    value = str(value or "").strip()

    if not value:
        return []

    # Backward compatibility for previously stored JSON.
    try:
        existing = json.loads(value)

        if isinstance(existing, dict):
            existing = existing.get("turns", [])

        if isinstance(existing, list):
            result: List[Dict[str, str]] = []

            for turn in existing:
                if not isinstance(turn, dict):
                    continue

                result.append(
                    {
                        "user": _normalize_message_text(
                            turn.get("user", "")
                        ),
                        "assistant": _normalize_message_text(
                            turn.get("assistant", "")
                        ),
                    }
                )

            return result
    except (json.JSONDecodeError, TypeError):
        pass

    conversation: List[Dict[str, str]] = []

    sections = re.split(
        r"\n\n─+\n\n",
        value,
    )

    for section in sections:
        match = re.match(
            r"USER:\n(.*?)\n\nASSISTANT:\n(.*)",
            section,
            flags=re.DOTALL,
        )

        if not match:
            continue

        conversation.append(
            {
                "user": match.group(1).strip(),
                "assistant": match.group(2).strip(),
            }
        )

    return conversation


@lru_cache(maxsize=1)
def _get_worksheet():
    credentials = Credentials.from_service_account_file(
        str(_credentials_path()),
        scopes=SHEETS_SCOPES,
    )

    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(settings.google_sheet_id)

    try:
        worksheet = spreadsheet.worksheet(
            settings.google_worksheet_name
        )
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=settings.google_worksheet_name,
            rows=1000,
            cols=len(HEADERS),
        )

    existing_headers = worksheet.row_values(1)

    if not existing_headers:
        worksheet.update(
            range_name="A1:E1",
            values=[HEADERS],
        )

    elif existing_headers[: len(LEGACY_HEADERS)] == LEGACY_HEADERS:
        worksheet.insert_cols(
            [["session_id"]],
            col=2,
        )

    elif existing_headers[: len(HEADERS)] != HEADERS:
        raise ValueError(
            f"Worksheet '{settings.google_worksheet_name}' has "
            f"unexpected headers. Expected: {HEADERS}"
        )

    return worksheet


def _find_session_row(
    worksheet,
    user_id: str,
    session_id: str,
) -> Tuple[Optional[int], Optional[List[Dict[str, str]]]]:
    records = worksheet.get_all_records()

    for row_number, row in enumerate(records, start=2):
        stored_user_id = str(row.get("user_id", "")).strip()
        stored_session_id = str(
            row.get("session_id", "")
        ).strip()

        if stored_user_id != user_id:
            continue

        if stored_session_id != session_id:
            continue

        conversation = _parse_display_conversation(
            row.get("conversation_json", "")
        )

        return row_number, conversation

    return None, None


def load_today_chat(
    user_id: str,
    session_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    normalized_user_id = (
        str(user_id or "guest_user").strip() or "guest_user"
    )
    normalized_session_id = str(session_id or "").strip()

    if not normalized_session_id:
        return []

    with _STORAGE_LOCK:
        worksheet = _get_worksheet()

        _, conversation = _find_session_row(
            worksheet,
            normalized_user_id,
            normalized_session_id,
        )

    return conversation or []


def append_turn(
    user_id: str,
    session_id: Optional[str],
    user_message: str,
    assistant_reply: str,
) -> None:
    normalized_user_id = (
        str(user_id or "guest_user").strip() or "guest_user"
    )
    normalized_session_id = str(session_id or "").strip()

    if not normalized_session_id:
        raise ValueError(
            "session_id is required to save the conversation"
        )

    current_time = _now()
    current_date = current_time.date().isoformat()
    formatted_time = current_time.strftime("%I:%M:%S %p")

    new_turn = {
        "user": _normalize_message_text(user_message),
        "assistant": _normalize_message_text(assistant_reply),
    }

    with _STORAGE_LOCK:
        worksheet = _get_worksheet()

        row_number, conversation = _find_session_row(
            worksheet,
            normalized_user_id,
            normalized_session_id,
        )

        conversation = conversation or []
        conversation.append(new_turn)

        readable_conversation = _conversation_to_display(
            conversation
        )

        if row_number is None:
            worksheet.append_row(
                [
                    normalized_user_id,
                    normalized_session_id,
                    current_date,
                    formatted_time,
                    readable_conversation,
                ],
                value_input_option="RAW",
            )
            return

        worksheet.update(
            range_name=f"D{row_number}:E{row_number}",
            values=[
                [
                    formatted_time,
                    readable_conversation,
                ]
            ],
            value_input_option="RAW",
        )