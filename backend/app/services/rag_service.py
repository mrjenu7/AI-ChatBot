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


def get_service_options() -> List[Dict[str, str]]:
    """Build selectable service options directly from the loaded knowledge base."""
    options: List[Dict[str, str]] = []
    for chunk in load_knowledge_chunks():
        category = str(chunk.get("category", "")).strip()
        title = str(chunk.get("title", "")).strip()
        service_id = str(chunk.get("id", "")).strip()
        if not service_id or not title or not category:
            continue
        if category in {"Corporate", "Overview", "Careers", "Portfolio"}:
            continue
        if "overview" in title.lower():
            continue
        raw_url = str(chunk.get("url", "")).split(",", 1)[0].strip()
        service_url = raw_url if raw_url.startswith("/") and not raw_url.startswith("//") else ""
        options.append({"id": service_id, "title": title, "category": category, "url": service_url})
    return options


def get_service_option(service_id: Optional[str]) -> Optional[Dict[str, str]]:
    if not service_id:
        return None
    return next((option for option in get_service_options() if option["id"] == service_id), None)


def get_service_links_from_context(context: str, limit: int = 3) -> List[Dict[str, str]]:
    """Resolve retrieved service headings to safe relative website links."""
    by_title = {option["title"]: option for option in get_service_options()}
    links: List[Dict[str, str]] = []
    for title in re.findall(r"^###\s+(.+?)\s*$", context or "", flags=re.MULTILINE):
        option = by_title.get(title.strip())
        if not option or not option.get("url"):
            continue
        links.append({"title": option["title"], "url": option["url"]})
        if len(links) >= limit:
            break
    return links


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

# Broad request/industry terms are useful context but too common to identify a
# particular service page on their own.
GENERIC_QUERY_TERMS = {
    "solution", "solutions", "service", "services", "need", "want", "help",
    "business", "brand", "marketing", "product", "products", "fashion",
    "designer", "design", "company", "provide", "offer", "work", "make",
    "build", "create", "develop", "development", "use", "using", "about",
}

# Service concepts commonly used by prospective customers, including romanized
# Gujarati/Hindi phrasing. Keep these aliases mapped to KB records so the
# unfiltered ("All services") flow can find service details without a UI filter.
SERVICE_INTENT_ALIASES = {
    "ar_development_services": {
        "ar", "augmented reality", "webar", "ar try on", "try on", "try-on",
        "fitting app", "virtual fitting", "kapda try", "kapde try", "kapde pehen",
        "kapda peher", "mobile par kapda", "ring try", "jewellery try",
        "jewelry try", "real world digital", "real-world digital",
    },
    "vr_development_services": {"vr", "virtual reality", "virtual reality simulator"},
    "mobile_app_development_services": {"mobile app", "mobile application", "android app", "iphone app"},
    "web_development_services": {"website", "web site", "online website"},
    "shopify_development_services": {"shopify", "online store", "ecommerce store", "e-commerce store"},
    "seo_optimization_services": {"seo", "google ranking", "rank on google", "google par rank"},
    "ai_development_services": {"artificial intelligence", "machine learning", "custom ai"},
}


def _route_service_intent(query: str, chunks: List[Dict]) -> List[Dict]:
    """Route clear service-intent language to relevant service KB records."""
    text = (query or "").lower()
    normalized = re.sub(r"[\s_-]+", " ", text)
    by_id = {str(chunk.get("id", "")): chunk for chunk in chunks}
    matched: List[Dict] = []
    for chunk_id, aliases in SERVICE_INTENT_ALIASES.items():
        if any(re.search(r"(?<!\w)" + re.escape(re.sub(r"[\s_-]+", " ", alias.lower())) + r"(?!\w)", normalized) for alias in aliases):
            chunk = by_id.get(chunk_id)
            if chunk:
                matched.append(chunk)
    return matched


def _tokenize(text: str) -> List[str]:
    """Tokenize Latin and Indic-script text without depending on query language."""
    return re.findall(r'[\w\u0A80-\u0AFF\u0900-\u097F]+', (text or '').lower())


def _route_general_company_query(query: str, chunks: List[Dict]) -> List[Dict]:
    """Route broad company, contact, and careers questions to their source records."""
    text = (query or "").lower()
    words = set(_tokenize(text))
    by_id = {str(chunk.get("id", "")): chunk for chunk in chunks}

    career_terms = {"career", "careers", "job", "jobs", "vacancy", "vacancies", "hiring", "internship", "internships", "nokri", "naukri"}
    if words & career_terms:
        result = []
        for chunk_id in ("careers_culture_and_work_life", "company_identity_and_contact"):
            if chunk_id in by_id:
                result.append(by_id[chunk_id])
        if result:
            return result

    contact_terms = {"quote", "quotation", "contact", "email", "phone", "call", "urgent", "representative", "person", "saheb", "vaat"}
    if words & contact_terms or "talk to someone" in text or "speak to someone" in text:
        identity = by_id.get("company_identity_and_contact")
        return [identity] if identity else []

    overview_phrases = (
        "what does we3vision do", "what does your company do", "what do you do",
        "main service", "primary service", "company shu kare", "company su kare",
        "shu kaam", "su kaam", "company vishe", "about we3vision", "about your company",
    )
    broad_company = any(phrase in text for phrase in overview_phrases)
    if broad_company:
        result = []
        for chunk_id in ("core_services_overview", "company_identity_and_contact"):
            if chunk_id in by_id:
                result.append(by_id[chunk_id])
        if result:
            return result
    return []


def retrieve_relevant_context(
    query: str,
    top_k: int = 1,
    max_context_chars: int = 3200,
    selected_service_id: Optional[str] = None,
) -> str:
    """
    RAG Retrieval: Given a user message, score and retrieve the most relevant
    knowledge chunks from the We3vision knowledge base.
    """
    if not query or not query.strip():
        return ""

    chunks = load_knowledge_chunks()
    selected_service = get_service_option(selected_service_id)
    clean_query = query.lower()
    # Extract words/tokens (handles Latin words and non-ASCII script tokens like Gujarati/Hindi)
    query_tokens = _tokenize(clean_query)
    meaningful_tokens = {
        token for token in query_tokens
        if len(token) >= 2 and token not in STOP_WORDS
    }
    specific_tokens = meaningful_tokens - GENERIC_QUERY_TERMS

    scored_chunks = []

    for chunk in chunks:
        score = 0
        keywords = [k.lower() for k in chunk.get("keywords", [])]
        content_lower = chunk.get("content", "").lower()
        title_lower = chunk.get("title", "").lower()

        # Multi-word phrase matching (e.g., "website redesign", "cloud migration")
        # Reward multiword keywords and service names strongly, while avoiding
        # substring collisions (e.g. "art" matching "marketing").
        for kw in keywords:
            keyword_tokens = set(_tokenize(kw))
            if " " in kw and kw in clean_query:
                score += 12
            elif keyword_tokens and keyword_tokens.issubset(meaningful_tokens):
                score += 8

        for token in query_tokens:
            if len(token) < 2 or token in STOP_WORDS:
                continue

            # Exact match in keyword list (highest weight)
            if token in keywords:
                score += 8
            elif any(token in _tokenize(kw) for kw in keywords):
                score += 4

            # Match in chunk title
            if token in title_lower:
                score += 7 if token in specific_tokens else 1

            # Match in chunk content
            if token in content_lower:
                score += 1

        # Give category a small signal; content-only matches stay weak so a
        # long unrelated page cannot win solely by repeating generic words.
        category_tokens = set(_tokenize(chunk.get("category", "")))
        score += 2 * len(meaningful_tokens & category_tokens)

        # Common marketing requests often include no service-specific wording.
        # Prefer marketing pages for those requests instead of unrelated pages
        # that happen to mention products or businesses.
        if meaningful_tokens & {"marketing", "advertising", "campaign"}:
            if "marketing" in category_tokens:
                score += 9

        scored_chunks.append((score, chunk))

    # Stable, deterministic tie-break by identifier rather than KB file order.
    scored_chunks.sort(key=lambda x: (-x[0], str(x[1].get("id", ""))))

    # Prefer an explicit service intent over generic contact routing. For
    # example, "works on every phone?" contains "phone" but is an AR question,
    # not a request for company contact details.
    service_intent_chunks = _route_service_intent(query, chunks)
    # For broad company intents, use canonical records instead of whichever
    # service page happens to share generic words with the query.
    routed_chunks = _route_general_company_query(query, chunks)
    if selected_service:
        selected_chunk = next((chunk for chunk in chunks if chunk.get("id") == selected_service["id"]), None)
        selected_chunks = [selected_chunk] if selected_chunk else []
    elif service_intent_chunks:
        selected_chunks = service_intent_chunks[:top_k]
    elif routed_chunks:
        selected_chunks = routed_chunks
    else:
        # Service pages need a stronger match than a generic word in long page
        # content. Avoid injecting unrelated pages for off-topic prose.
        selected_chunks = [
            chunk for score, chunk in scored_chunks
            if score >= 9 and chunk.get("id") != "core_services_overview"
        ][:top_k]

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

    # Bound context size so a large service page cannot exhaust the model's TPM
    # budget. Prefer whole chunks; if the best chunk alone is large, truncate it
    # with an explicit note that the remainder was omitted.
    context_parts = []
    remaining_chars = max_context_chars
    for c in selected_chunks:
        heading = f"### {c.get('title')}\n"
        content = str(c.get("content", ""))
        available = remaining_chars - len(heading)
        if available <= 0:
            break
        if len(content) > available:
            marker = "\n[Additional source text omitted to keep the request within context limits.]"
            content = content[:max(0, available - len(marker))].rstrip() + marker
        part = heading + content
        context_parts.append(part)
        remaining_chars -= len(part) + 2
        if remaining_chars <= 0 or len(part) < len(heading) + len(str(c.get("content", ""))):
            break

    return "\n\n".join(context_parts)
