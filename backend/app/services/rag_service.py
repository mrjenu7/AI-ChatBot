import json
import re
from pathlib import Path
from typing import List, Dict, Optional

try:
    import pypdf
except ImportError:
    pypdf = None

# Path to the structured knowledge base
KNOWLEDGE_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "we3vision_knowledge_base.json"
PDF_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "we3vision_knowledge_base.pdf"

_CHUNKS_CACHE: Optional[List[Dict]] = None


def load_knowledge_chunks(force_reload: bool = False) -> List[Dict]:
    """Load and cache knowledge chunks from data/we3vision_knowledge_base.json."""
    global _CHUNKS_CACHE
    if _CHUNKS_CACHE is not None and not force_reload:
        return _CHUNKS_CACHE

    if KNOWLEDGE_JSON_PATH.exists():
        try:
            content = KNOWLEDGE_JSON_PATH.read_text(encoding="utf-8")
            _CHUNKS_CACHE = json.loads(content)
            if _CHUNKS_CACHE:
                return _CHUNKS_CACHE
        except Exception as e:
            print(f"[RAG] Error reading knowledge base JSON: {e}")

    # Direct fallback: extract chunks from backend/data/we3vision_knowledge_base.pdf
    if PDF_PATH.exists() and pypdf is not None:
        try:
            reader = pypdf.PdfReader(str(PDF_PATH))
            pdf_chunks = []
            for i, page in enumerate(reader.pages):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pdf_chunks.append({
                        "id": f"pdf_page_{i+1}",
                        "title": f"We3vision Knowledge Base (Page {i+1})",
                        "keywords": [w.lower() for w in re.findall(r'\b[A-Za-z]{3,}\b', txt)[:20]],
                        "content": txt
                    })
            if pdf_chunks:
                _CHUNKS_CACHE = pdf_chunks
                return _CHUNKS_CACHE
        except Exception as e:
            print(f"[RAG] Error reading from PDF directly: {e}")

    # Fallback to basic canonical knowledge if file not found
    _CHUNKS_CACHE = [
        {
            "id": "canonical_fallback",
            "title": "We3vision Canonical Profile",
            "keywords": ["company", "we3vision", "services", "surat", "contact"],
            "content": (
                "Company: We3vision Private Limited\n"
                "Headquarters: Surat, Gujarat, India (Nanpura)\n"
                "Germany Location: Marburg, Germany\n"
                "Email: info@we3vision.com | Phone: +91 7383216096\n"
                "Services: Metaverse, CRM Development, Web Development, Mobile Apps, AR/VR, "
                "2D/3D Animation & CGI, UI/UX Design, AI Development, Enterprise Software (ERP/SaaS)."
            )
        }
    ]
    return _CHUNKS_CACHE


def reload_knowledge_base() -> List[Dict]:
    """Force reload the knowledge base chunks from disk."""
    return load_knowledge_chunks(force_reload=True)


STOP_WORDS = {
    "who", "what", "where", "when", "why", "how", "is", "are", "the", "and",
    "for", "with", "can", "you", "does", "did", "was", "were", "this", "that",
    "our", "your", "tell", "give", "from", "about", "have", "has", "had", "will",
    "would", "should", "some", "any", "more", "most", "much", "many", "all", "world"
}


def retrieve_relevant_context(query: str, top_k: int = 2) -> str:
    """
    RAG Retrieval: Given a user message, score and retrieve the most relevant
    knowledge chunks from the We3vision knowledge base.
    """
    if not query or not query.strip():
        return ""

    chunks = load_knowledge_chunks()
    clean_query = query.lower()
    # Extract words/tokens (handles Latin words and non-ASCII script tokens like Gujarati/Hindi)
    query_tokens = re.findall(r'[\w\u0A80-\u0AFF\u0900-\u097F]+', clean_query)

    scored_chunks = []

    for chunk in chunks:
        score = 0
        keywords = [k.lower() for k in chunk.get("keywords", [])]
        content_lower = chunk.get("content", "").lower()
        title_lower = chunk.get("title", "").lower()

        # Multi-word phrase matching (e.g., "website redesign", "cloud migration")
        for kw in keywords:
            if " " in kw and kw in clean_query:
                score += 8

        for token in query_tokens:
            if len(token) < 2 or token in STOP_WORDS:
                continue

            # Exact match in keyword list (highest weight)
            if token in keywords:
                score += 5
            elif any(token in kw for kw in keywords):
                score += 3

            # Match in chunk title
            if token in title_lower:
                score += 3

            # Match in chunk content
            if token in content_lower:
                score += 1

        scored_chunks.append((score, chunk))

    # Sort by relevance score descending
    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    # Select top chunks with a positive score
    selected_chunks = [chunk for score, chunk in scored_chunks if score > 0][:top_k]

    # If no specific keyword matched:
    if not selected_chunks:
        # If it's a general company inquiry or greeting, provide overview
        general_indicators = ["we3vision", "company", "કંપની", "વિશે", "about", "hi", "hello", "hey", "નમસ્તે", "કેમ છો", "नमस्ते"]
        if any(w in clean_query for w in general_indicators):
            selected_chunks = [chunks[0], chunks[1]] if len(chunks) > 1 else [chunks[0]]
        else:
            return (
                "NOTE: No matching records were found in the We3vision knowledge base for this inquiry. "
                "If this is an out-of-scope or non-company inquiry (not about We3vision), strictly decline to answer "
                "per Business Agent Rule 2."
            )

    # Format the retrieved context for prompt injection
    context_parts = []
    for c in selected_chunks:
        context_parts.append(f"### {c.get('title')}\n{c.get('content')}")

    return "\n\n".join(context_parts)
