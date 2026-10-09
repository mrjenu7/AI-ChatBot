from typing import TypedDict, List, Dict, Optional, Any


class AgentState(TypedDict):
    """LangGraph state tracking data across workflow nodes."""
    user_id: str
    session_id: Optional[str]
    message: str
    selected_service_id: Optional[str]
    history: List[Dict[str, str]]
    rag_context: str
    language: Dict[str, Any]
    reply: str
    scope: str
