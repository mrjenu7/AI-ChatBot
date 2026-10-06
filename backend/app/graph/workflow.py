from langgraph.graph import StateGraph, START, END
from app.graph.state import AgentState
from app.graph.nodes import (
    detect_language_node,
    load_history_node,
    company_scope_node,
    retrieve_rag_node,
    generate_response_node,
    save_supabase_node,
)


def create_chat_workflow():
    """Build and compile the multilingual business-agent workflow."""
    workflow = StateGraph(AgentState)

    workflow.add_node("detect_language", detect_language_node)
    workflow.add_node("company_scope", company_scope_node)
    workflow.add_node("load_history", load_history_node)
    workflow.add_node("retrieve_rag", retrieve_rag_node)
    workflow.add_node("generate_response", generate_response_node)
    workflow.add_node("save_supabase", save_supabase_node)

    workflow.add_edge(START, "detect_language")
    workflow.add_edge("detect_language", "load_history")
    workflow.add_edge("load_history", "company_scope")
    workflow.add_conditional_edges(
        "company_scope",
        lambda state: "save_supabase" if state.get("scope") in {"OUT_OF_SCOPE", "AMBIGUOUS"} else "retrieve_rag",
        {"save_supabase": "save_supabase", "retrieve_rag": "retrieve_rag"},
    )
    workflow.add_edge("retrieve_rag", "generate_response")
    workflow.add_edge("generate_response", "save_supabase")
    workflow.add_edge("save_supabase", END)

    return workflow.compile()


chat_graph = create_chat_workflow()
