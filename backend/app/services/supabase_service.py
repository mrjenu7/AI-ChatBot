import re
import unicodedata
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.core.config import settings

if TYPE_CHECKING:
    from supabase import Client


_TABLE = "chat_conversations"


def _get_client() -> "Client":
    from supabase import create_client

    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is not configured")

    if not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY is not configured")

    return create_client(
        settings.supabase_url,
        settings.supabase_service_key,
    )


def _normalize_uuid(value: Optional[str], field_name: str) -> str:
    try:
        return str(UUID(str(value).strip()))
    except (AttributeError, ValueError, TypeError):
        raise ValueError(f"{field_name} must be a valid UUID")


def _normalize_message_text(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.*?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^[ \t]*[*•][ \t]+", "- ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.app_timezone))


def load_conversation(
    user_id: str,
    session_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    normalized_user_id = _normalize_uuid(user_id, "user_id")
    if not session_id:
        return []

    normalized_session_id = _normalize_uuid(session_id, "session_id")
    client = _get_client()

    response = (
        client.table(_TABLE)
        .select("conversation")
        .eq("user_id", normalized_user_id)
        .eq("session_id", normalized_session_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        return []

    conversation = response.data[0].get("conversation") or []
    if not isinstance(conversation, list):
        return []

    return [
        {
            "user": str(turn.get("user", "")),
            "assistant": str(turn.get("assistant", "")),
        }
        for turn in conversation
        if isinstance(turn, dict)
    ]


def append_turn(
    user_id: str,
    session_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    normalized_user_id = _normalize_uuid(user_id, "user_id")
    normalized_session_id = _normalize_uuid(session_id, "session_id")

    client = _get_client()
    current_time = _now()

    existing_response = (
        client.table(_TABLE)
        .select("id, user_id, session_id, conversation")
        .eq("user_id", normalized_user_id)
        .eq("session_id", normalized_session_id)
        .limit(1)
        .execute()
    )

    existing = existing_response.data[0] if existing_response.data else None

    conversation = existing.get("conversation") if existing else []
    if not isinstance(conversation, list):
        conversation = []

    conversation.append(
        {
            "user": _normalize_message_text(user_message),
            "assistant": _normalize_message_text(assistant_reply),
        }
    )

    payload = {
        "user_id": normalized_user_id,
        "session_id": normalized_session_id,
        "date": current_time.date().isoformat(),
        "time": current_time.strftime("%H:%M:%S"),
        "conversation": conversation,
        "updated_at": current_time.isoformat(),
    }

    if existing:
        client.table(_TABLE).update(payload).eq(
            "user_id", normalized_user_id
        ).eq(
            "session_id", normalized_session_id
        ).execute()
    else:
        payload["id"] = str(uuid4())
        client.table(_TABLE).insert(payload).execute()


def get_lead_by_session(session_id: str) -> Optional[Dict]:
    """
    Get the existing lead for a chat session.
    Returns None when no lead exists yet.
    """
    normalized_session_id = _normalize_uuid(session_id, "session_id")
    client = _get_client()

    response = (
        client.table("chat_leads")
        .select(
            "id, session_id, name, email, phone, company, "
            "inquiry_type, requirement, status, created_at, updated_at"
        )
        .eq("session_id", normalized_session_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def upsert_lead(
    session_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    requirement: Optional[str] = None,
    status: str = "new",
) -> Dict:
    """
    Create or update the lead belonging to a chat session.

    Existing values are preserved when the new value is empty.
    """

    normalized_session_id = _normalize_uuid(session_id, "session_id")
    client = _get_client()

    # Find existing lead
    existing_response = (
        client.table("chat_leads")
        .select(
            "id, session_id, name, email, phone, company, "
            "inquiry_type, requirement, status"
        )
        .eq("session_id", normalized_session_id)
        .limit(1)
        .execute()
    )

    existing = (
        existing_response.data[0]
        if existing_response.data
        else None
    )

    def merge(new_value, old_value):
        """
        Keep the old value when the new value is empty.
        """
        if new_value is None:
            return old_value

        value = str(new_value).strip()

        if not value:
            return old_value

        return value

    if existing:
        payload = {
            "name": merge(name, existing.get("name")),
            "email": merge(email, existing.get("email")),
            "phone": merge(phone, existing.get("phone")),
            "company": merge(company, existing.get("company")),
            "inquiry_type": merge(
                inquiry_type,
                existing.get("inquiry_type"),
            ),
            "requirement": merge(
                requirement,
                existing.get("requirement"),
            ),
            "status": status or existing.get("status") or "new",
        }

        response = (
            client.table("chat_leads")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )

        return response.data[0] if response.data else {
            **existing,
            **payload,
        }

    payload = {
        "id": str(uuid4()),
        "session_id": normalized_session_id,
        "name": name,
        "email": email,
        "phone": phone,
        "company": company,
        "inquiry_type": inquiry_type,
        "requirement": requirement,
        "status": status or "new",
    }

    response = (
        client.table("chat_leads")
        .insert(payload)
        .execute()
    )

    return response.data[0] if response.data else payload


# Keep backward compatibility if anything else in the project
# still calls create_lead().
def create_lead(
    session_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    requirement: Optional[str] = None,
    status: str = "new",
) -> Dict:
    return upsert_lead(
        session_id=session_id,
        name=name,
        email=email,
        phone=phone,
        company=company,
        inquiry_type=inquiry_type,
        requirement=requirement,
        status=status,
    )