import pytest
from app.services.rag_service import retrieve_relevant_context, load_knowledge_chunks, reload_knowledge_base


@pytest.fixture(autouse=True)
def reload_chunks():
    reload_knowledge_base()


def test_knowledge_base_loaded_completely():
    chunks = load_knowledge_chunks()
    assert len(chunks) >= 40
    chunk_ids = {c["id"] for c in chunks}
    expected_ids = {
        "company_identity_and_contact",
        "core_services_overview",
        "brand_identity_and_rebranding",
        "graphics_ui_ux_design",
        "animation_services_2d_3d",
        "cgi_video_production_services",
        "modeling_services_3d",
        "website_redesign_services",
        "web_development_services",
        "mobile_app_development_services",
        "software_development_services",
        "custom_development_services",
        "low_code_development_services",
        "saas_development_services",
        "shopify_development_services",
        "wordpress_development_services",
        "technology_migration_services",
        "erp_solutions_services",
        "erp_development_services",
        "crm_development_services",
        "digital_marketing_services",
        "seo_optimization_services",
        "immersive_marketing_services",
        "ai_development_services",
        "generative_ai_services",
        "ai_agents_services",
        "rag_ai_services",
        "machine_learning_services",
        "computer_vision_services",
        "ai_automation_services",
        "mlops_services",
        "ar_development_services",
        "vr_development_services",
        "mr_mixed_reality_solutions",
        "xr_extended_reality_solutions",
        "metaverse_solutions",
        "immersive_services",
        "android_game_development",
        "ios_game_development",
        "metaverse_games_development",
        "nft_game_development",
        "nft_marketplace_development",
        "featured_projects_and_track_record",
    }
    assert expected_ids.issubset(chunk_ids)


@pytest.mark.parametrize("query,expected_keyword", [
    ("What is your website redesign process?", "Website Redesign Services"),
    ("Can you migrate our legacy database to the cloud?", "Technology Migration Services"),
    ("Do you offer brand identity and brand guidelines?", "Brand Identity & Rebranding Services"),
    ("Tell me about 2D and 3D animation services", "2D & 3D Animation Services"),
    ("Can you produce CGI video commercials for products?", "CGI & Video Production Services"),
    ("What tools do you use for UI/UX design and prototyping?", "Graphics & UI/UX Design Services"),
    ("Do you offer AR try-on for ecommerce?", "AR (Augmented Reality) Development Services"),
    ("Can you develop VR training for Oculus or Meta Quest?", "VR (Virtual Reality) Development Services"),
    ("What are your Metaverse solutions and virtual worlds?", "Metaverse Solutions & Virtual Worlds"),
    ("Do you offer NFT game development?", "NFT Game Development"),
    ("Can you build an NFT marketplace for digital assets?", "NFT Marketplace Development"),
    ("What is immersive marketing and interactive campaigns?", "Immersive Marketing Services"),
    ("Can you develop metaverse games?", "Metaverse Games Development"),
    ("Where is We3vision headquarters located?", "Company Identity, Location & Contact Details"),
    ("Who founded We3vision and what is the CIN number?", "Company Identity, Location & Contact Details"),
    ("Tell me about coal mining VR project", "Featured Projects, Portfolio & Track Record"),
    ("Can you build autonomous AI agents with LangGraph?", "AI Agents Development Services"),
    ("How do you implement retrieval augmented generation (RAG) with vector databases?", "Retrieval-Augmented Generation (RAG AI) Services"),
    ("Do you offer Shopify store development and custom theme design?", "Shopify eCommerce Development Services"),
    ("Can you help with MLOps and production model deployment pipelines?", "MLOps & AI Infrastructure Services"),
    ("Tell me about your custom ERP development and solutions", "ERP"),
    ("What web development frameworks do you use for fast websites?", "Web Development Services"),
    ("Do you build iOS and Android apps with Flutter and React Native?", "Mobile App Development Services"),
    ("Can you build custom software for enterprise workflows?", "Custom Software Development Services"),
    ("Can you build apps with Bubble or Webflow without heavy coding?", "Low-Code Development Services"),
    ("How do you build scalable multi-tenant SaaS products?", "SaaS Product Development Services"),
    ("Do you build custom WordPress and WooCommerce sites?", "WordPress & CMS Development Services"),
    ("Can you build a custom sales CRM for lead tracking?", "CRM Development Services"),
    ("What digital marketing and paid ad strategies do you offer?", "Digital Marketing Services"),
    ("How do you optimize websites for SEO and organic Google ranking?", "Search Engine Optimization (SEO) Services"),
    ("Can you build enterprise LLM and generative AI applications?", "Generative AI Development Services"),
    ("Do you develop predictive machine learning models for forecasting?", "Machine Learning (ML) Solutions"),
    ("Can you build computer vision systems for OCR and image recognition?", "Computer Vision Services"),
    ("How can AI automation streamline document processing workflows?", "AI Automation & Workflow Services"),
    ("Do you develop Android games with Unity or Unreal?", "Android Game Development Services"),
    ("Can you build iOS games using Swift and SpriteKit?", "iOS Game Development Services"),
    ("What are your Mixed Reality MR solutions with MRTK?", "Mixed Reality (MR) Solutions"),
    ("Do you deliver cross-platform extended reality XR solutions?", "Extended Reality (XR) Solutions"),
])
def test_retrieval_service_matches_english(query, expected_keyword):
    context = retrieve_relevant_context(query)
    assert expected_keyword in context, f"Query '{query}' did not retrieve '{expected_keyword}'. Context:\n{context[:300]}"


@pytest.mark.parametrize("query,expected_keyword", [
    ("વેબસાઇટ રિડિઝાઇન કરવાની સેવાઓ વિશે જણાવો", "Website Redesign Services"),
    ("બ્રાન્ડિંગ અને લોગો ડિઝાઇન માટે શું છે?", "Brand Identity & Rebranding Services"),
    ("ક્લાઉડ માઈગ્રેશન અને ડેટાબેઝ માઈગ્રેશન", "Technology Migration Services"),
    ("3ડી મોડેલિંગ અને એનિમેશન", "Animation Services"),
    ("સુરત ઓફિસનું સરનામું શું છે?", "Company Identity, Location & Contact Details"),
])
def test_retrieval_service_matches_gujarati(query, expected_keyword):
    context = retrieve_relevant_context(query)
    assert expected_keyword in context, f"Gujarati Query '{query}' did not retrieve '{expected_keyword}'. Context:\n{context[:300]}"


@pytest.mark.parametrize("query,expected_keyword", [
    ("वेबसाइट रीडिजाइन प्रक्रिया क्या है?", "Website Redesign Services"),
    ("कंपनी का पता और संपर्क विवरण क्या है?", "Company Identity, Location & Contact Details"),
    ("मेटावर्स समाधान और वर्चुअल दुनिया", "Metaverse Solutions & Virtual Worlds"),
])
def test_retrieval_service_matches_hindi(query, expected_keyword):
    context = retrieve_relevant_context(query)
    assert expected_keyword in context, f"Hindi Query '{query}' did not retrieve '{expected_keyword}'. Context:\n{context[:300]}"


def test_out_of_scope_query_declined():
    context = retrieve_relevant_context("Who won the 2024 cricket world cup?")
    assert "No matching records were found" in context or "strictly decline" in context


def test_leadership_retrieval():
    context = retrieve_relevant_context("Who is the director of We3vision?")
    assert "Parth Patel" in context
    assert "Company Identity, Location & Contact Details" in context


def test_pdf_file_and_fallback(monkeypatch):
    import pypdf
    from app.services import rag_service

    # Verify PDF file has exactly 184 pages
    assert rag_service.PDF_PATH.exists()
    reader = pypdf.PdfReader(str(rag_service.PDF_PATH))
    assert len(reader.pages) == 184

    # Verify fallback to PDF if JSON is unavailable
    monkeypatch.setattr(rag_service, "KNOWLEDGE_JSON_PATH", rag_service.PDF_PATH.parent / "non_existent.json")
    chunks = rag_service.load_knowledge_chunks(force_reload=True)
    assert len(chunks) == 184
    assert chunks[0]["id"] == "pdf_page_1"
    assert "We3vision" in chunks[0]["content"]

