#!/usr/bin/env python3
"""
build_knowledge_base.py
Builds the structured knowledge base JSON (backend/data/we3vision_knowledge_base.json)
by extracting and structuring content directly from the 179-page PDF
(backend/data/we3vision_knowledge_base.pdf).
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Dict

try:
    import pypdf
except ImportError:
    print("[ERROR] pypdf is required. Run: pip install pypdf")
    sys.exit(1)

BACKEND_DIR = Path(__file__).resolve().parent
if BACKEND_DIR.name == "services":
    BACKEND_DIR = BACKEND_DIR.parent.parent
elif BACKEND_DIR.name != "backend":
    if (BACKEND_DIR / "backend").exists():
        BACKEND_DIR = BACKEND_DIR / "backend"

DATA_DIR = BACKEND_DIR / "data"
PDF_PATH = DATA_DIR / "we3vision_knowledge_base.pdf"
JSON_OUTPUT_PATH = DATA_DIR / "we3vision_knowledge_base.json"

SERVICE_METADATA_DEFS = [
    {
        "num": 1,
        "id": "brand_identity_and_rebranding",
        "title": "Brand Identity & Rebranding Services",
        "category": "Design & Creative",
        "url": "/brand-identity",
        "keywords": [
            "brand", "branding", "brand identity", "rebranding", "logo", "logo design",
            "visual identity", "brand guidelines", "typography", "color palette", "brand assets",
            "collateral design", "social media creative", "style guide", "corporate identity",
            "બ્રાન્ડ", "બ્રાન્ડિંગ", "લોગો", "બ્રાન્ડ આઇડેન્ટિટી", "રીબ્રાન્ડિંગ", "ડિઝાઇન",
            "ब्रांड", "ब्रांडिंग", "लोगो", "विजुअल पहचान", "रीब्रांडिंग"
        ]
    },
    {
        "num": 2,
        "id": "graphics_ui_ux_design",
        "title": "Graphics & UI/UX Design Services",
        "category": "Design & Creative",
        "url": "/graphics, /graphics-design, /ui-ux-design-services",
        "keywords": [
            "ui", "ux", "ui/ux", "graphics", "graphic design", "figma", "wireframes",
            "prototyping", "interface design", "user experience", "user interface",
            "web design", "mobile app design", "design system", "adobe xd", "sketch",
            "ગ્રાફિક્સ", "યુઆઇ", "યુએક્સ", "ડિઝાઇન", "પ્રોટોટાઇપ",
            "यूआई", "यूएक्स", "ग्राफिक डिजाइन", "वायरफ्रेम", "प्रोटोटाइपिंग"
        ]
    },
    {
        "num": 3,
        "id": "animation_services_2d_3d",
        "title": "2D & 3D Animation Services",
        "category": "Design & Creative",
        "url": "/animation",
        "keywords": [
            "animation", "2d animation", "3d animation", "motion graphics", "explainer video",
            "product animation", "character animation", "storyboard", "visual storytelling",
            "marketing video", "blender", "after effects", "maya",
            "એનિમેશન", "2d એનિમેશન", "3d એનિમેશન", "મોશન ગ્રાફિક્સ",
            "एनीमेशन", "2डी एनीमेशन", "3डी एनीमेशन", "मोशन ग्राफिक्स", "एनिमेटेड वीडियो"
        ]
    },
    {
        "num": 4,
        "id": "cgi_video_production_services",
        "title": "CGI & Video Production Services",
        "category": "Design & Creative",
        "url": "/cgi",
        "keywords": [
            "cgi", "video production", "computer graphics", "commercials", "vfx",
            "visual effects", "product visualization", "3d render", "video editing",
            "cinematic", "photorealistic", "commercial video", "social media video",
            "સીજીઆઈ", "વિડીયો પ્રોડક્શન", "વિઝ્યુઅલ ઇફેક્ટ્સ",
            "सीजीआई", "वीडियो प्रोडक्शन", "विजुअल इफेक्ट्स", "3डी रेंडरिंग"
        ]
    },
    {
        "num": 5,
        "id": "modeling_services_3d",
        "title": "3D Modeling Services",
        "category": "Design & Creative",
        "url": "/3d-modeling",
        "keywords": [
            "3d modeling", "3d model", "cad", "texturing", "lighting", "rigging",
            "photorealistic 3d", "product rendering", "assets", "low poly", "high poly",
            "ar assets", "game assets", "blender", "maya", "zbrush",
            "3d મોડેલિંગ", "3d મોડેલ", "ટેક્સચરિંગ",
            "3डी मॉडलिंग", "3डी मॉडल", "टेक्सचरिंग", "प्रोडक्ट रेंडरिंग"
        ]
    },
    {
        "num": 6,
        "id": "website_redesign_services",
        "title": "Website Redesign Services",
        "category": "Design & Creative",
        "url": "/redesign, /website-redesign",
        "keywords": [
            "redesign", "website redesign", "modernize website", "revamp website", "ui refresh",
            "responsive redesign", "seo redesign", "performance redesign", "fresh digital experience",
            "web overhaul", "conversion rate optimization",
            "વેબસાઇટ રિડિઝાઇન", "રિડિઝાઇન", "વેબસાઇટ અપગ્રેડ",
            "वेबसाइट रीडिजाइन", "रीडिजाइन", "वेबसाइट नवीनीकरण", "वेबसाइट अपग्रेड"
        ]
    },
    {
        "num": 7,
        "id": "web_development_services",
        "title": "Web Development Services",
        "category": "Web & Software Development",
        "url": "/webdev",
        "keywords": [
            "web development", "website", "react", "next.js", "frontend", "backend",
            "full stack", "custom website", "responsive web", "api", "node.js", "fast websites",
            "વેબ ડેવલપમેન્ટ", "વેબસાઇટ બનાવવી",
            "वेब डेवलपमेंट", "वेबसाइट विकास", "वेबसाइट निर्माण"
        ]
    },
    {
        "num": 8,
        "id": "mobile_app_development_services",
        "title": "Mobile App Development Services",
        "category": "Web & Software Development",
        "url": "/mobile",
        "keywords": [
            "mobile app", "app development", "ios app", "android app", "react native",
            "flutter", "cross platform", "swift", "kotlin", "play store", "app store",
            "મોબાઇલ એપ", "એપ ડેવલપમેન્ટ",
            "मोबाइल ऐप", "ऐप डेवलपमेंट"
        ]
    },
    {
        "num": 9,
        "id": "software_development_services",
        "title": "Custom Software Development Services",
        "category": "Web & Software Development",
        "url": "/software",
        "keywords": [
            "software development", "custom software", "enterprise software", "scalable software",
            "backend", "apis", ".net", "python", "docker",
            "સોફ્ટવેર ડેવલપમેન્ટ", "કસ્ટમ સોફ્ટવેર",
            "सॉफ्टवेयर डेवलपमेंट", "कस्टम सॉफ्टवेयर"
        ]
    },
    {
        "num": 10,
        "id": "custom_development_services",
        "title": "Tailored Custom Development Services",
        "category": "Web & Software Development",
        "url": "/custom-dev",
        "keywords": [
            "custom development", "tailored software", "bespoke solution", "agile development",
            "workflow automation", "api integrations",
            "કસ્ટમ ડેવલપમેન્ટ",
            "कस्टम डेवलपमेंट"
        ]
    },
    {
        "num": 11,
        "id": "low_code_development_services",
        "title": "Low-Code Development Services",
        "category": "Web & Software Development",
        "url": "/low-code",
        "keywords": [
            "low code", "no code", "bubble", "webflow", "make", "zapier", "airtable",
            "rapid mvp", "mvp development", "low-code",
            "લો કોડ", "નો કોડ",
            "लो कोड", "नो कोड"
        ]
    },
    {
        "num": 12,
        "id": "saas_development_services",
        "title": "SaaS Product Development Services",
        "category": "Web & Software Development",
        "url": "/Saas",
        "keywords": [
            "saas", "saas development", "software as a service", "multi tenant", "subscription billing",
            "cloud application", "scalable architecture",
            "સાસ ડેવલપમેન્ટ",
            "सास डेवलपमेंट"
        ]
    },
    {
        "num": 13,
        "id": "shopify_development_services",
        "title": "Shopify eCommerce Development Services",
        "category": "Web & Software Development",
        "url": "/shopify",
        "keywords": [
            "shopify", "shopify store", "ecommerce", "online store", "shopify plus",
            "shopify theme", "checkout optimization", "payment gateway",
            "શોપિફાય", "ઈકોમર્સ સ્ટોર",
            "शॉपिफाई", "ईकॉमर्स स्टोर"
        ]
    },
    {
        "num": 14,
        "id": "wordpress_development_services",
        "title": "WordPress & CMS Development Services",
        "category": "Web & Software Development",
        "url": "/wordpress",
        "keywords": [
            "wordpress", "woocommerce", "elementor", "cms", "wordpress development",
            "custom plugins", "custom themes", "blog website", "wp rocket",
            "વર્ડપ્રેસ", "વર્ડપ્રેસ ડેવલપમેન્ટ",
            "वर्डप्रेस", "वर्डप्रेस डेवलपमेंट"
        ]
    },
    {
        "num": 15,
        "id": "technology_migration_services",
        "title": "Technology Migration Services",
        "category": "Web & Software Development",
        "url": "/tech-migration, /technology-migration",
        "keywords": [
            "migration", "technology migration", "cloud migration", "database migration",
            "legacy modernization", "platform migration", "data migration", "zero downtime",
            "aws migration", "azure migration",
            "ટેકનોલોજી માઈગ્રેશન", "ક્લાઉડ માઈગ્રેશન", "ડેટાબેઝ માઈગ્રેશન",
            "टेक्नोलॉजी माइग्रेशन", "क्लाउड माइग्रेशन", "डेटाबेस माइग्रेशन"
        ]
    },
    {
        "num": 16,
        "id": "erp_solutions_services",
        "title": "Enterprise ERP Solutions",
        "category": "Enterprise Solutions",
        "url": "/erp-dev",
        "keywords": [
            "erp solutions", "erp", "enterprise resource planning", "inventory",
            "hr erp", "finance erp", "supply chain erp", "odoo", "erpnext",
            "ઈઆરપી", "ઈઆરપી સોલ્યુશન્સ",
            "ईआरपी", "ईआरपी सॉल्यूशंस"
        ]
    },
    {
        "num": 17,
        "id": "erp_development_services",
        "title": "Custom ERP Development Services",
        "category": "Enterprise Solutions",
        "url": "/erp",
        "keywords": [
            "erp development", "custom erp", "erp modules", "centralized erp",
            "on premise erp", "cloud erp", "workflow automation erp",
            "ઈઆરપી ડેવલપમેન્ટ",
            "ईआरपी डेवलपमेंट"
        ]
    },
    {
        "num": 18,
        "id": "crm_development_services",
        "title": "CRM Development Services",
        "category": "Enterprise Solutions",
        "url": "/crm",
        "keywords": [
            "crm", "crm development", "customer relationship management", "sales crm",
            "lead tracking", "pipeline management", "hubspot", "salesforce",
            "સીઆરએમ", "ગ્રાહક વ્યવસ્થાપન",
            "सीआरएम", "कस्टमर रिलेशनशिप मैनेजमेंट"
        ]
    },
    {
        "num": 19,
        "id": "digital_marketing_services",
        "title": "Digital Marketing Services",
        "category": "Marketing",
        "url": "/marketing",
        "keywords": [
            "marketing", "digital marketing", "social media marketing", "paid ads",
            "meta ads", "google ads", "content marketing", "growth marketing", "lead generation",
            "ડિજિટલ માર્કેટિંગ",
            "डिजिटल मार्केटिंग"
        ]
    },
    {
        "num": 20,
        "id": "seo_optimization_services",
        "title": "Search Engine Optimization (SEO) Services",
        "category": "Marketing",
        "url": "/seo",
        "keywords": [
            "seo", "search engine optimization", "google ranking", "technical seo",
            "on page seo", "off page seo", "backlinks", "keyword research", "organic traffic",
            "એસઇઓ",
            "एसईओ"
        ]
    },
    {
        "num": 21,
        "id": "immersive_marketing_services",
        "title": "Immersive Marketing Services",
        "category": "Marketing",
        "url": "/immersive-marketing",
        "keywords": [
            "immersive marketing", "interactive marketing", "ar marketing", "vr marketing",
            "metaverse marketing", "experiential marketing", "brand experience",
            "ઇમર્સિવ માર્કેટિંગ",
            "इमर्सिव मार्केटिंग"
        ]
    },
    {
        "num": 22,
        "id": "ai_development_services",
        "title": "Custom AI Development Services",
        "category": "AI & Machine Learning",
        "url": "/ai",
        "keywords": [
            "ai", "artificial intelligence", "ai development", "machine learning",
            "nlp", "deep learning", "predictive analytics", "custom ai", "tensorflow", "pytorch",
            "એઆઇ", "કૃત્રિમ બુદ્ધિમત્તા",
            "एआई", "आर्टिफिशियल इंटेलिजेंस"
        ]
    },
    {
        "num": 23,
        "id": "generative_ai_services",
        "title": "Generative AI Development Services",
        "category": "AI & Machine Learning",
        "url": "/generative-ai",
        "keywords": [
            "generative ai", "genai", "llm", "large language models", "chatgpt", "openai",
            "ai chatbots", "content generation", "code assistant", "multimodal",
            "જનરેટિવ એઆઇ", "એલએલએમ",
            "जेनेरेटिव एआई", "एलएलएम"
        ]
    },
    {
        "num": 24,
        "id": "ai_agents_services",
        "title": "AI Agents Development Services",
        "category": "AI & Machine Learning",
        "url": "/ai-agents",
        "keywords": [
            "ai agents", "autonomous agents", "multi agent systems", "agentic ai",
            "workflow agents", "customer support agents", "sales agents", "autonomous workflows",
            "એઆઇ એજન્ટ્સ", "ઓટોનોમસ એજન્ટ્સ",
            "एआई एजेंट्स", "ऑटोनॉमस एजेंट्स"
        ]
    },
    {
        "num": 25,
        "id": "rag_ai_services",
        "title": "Retrieval-Augmented Generation (RAG AI) Services",
        "category": "AI & Machine Learning",
        "url": "/rag-ai",
        "keywords": [
            "rag", "rag ai", "retrieval augmented generation", "vector database",
            "embeddings", "knowledge base ai", "document search", "semantic search", "pinecone", "chromadb",
            "આરએજી", "નોલેજ બેઝ એઆઇ", "વેક્ટર સર્ચ",
            "आरएजी", "वेक्टर डेटाबेस", "नॉलेज बेस एआई"
        ]
    },
    {
        "num": 26,
        "id": "machine_learning_services",
        "title": "Machine Learning (ML) Solutions",
        "category": "AI & Machine Learning",
        "url": "/machine-learning",
        "keywords": [
            "machine learning", "ml", "predictive models", "classification", "anomaly detection",
            "forecasting", "recommendation systems", "scikit-learn", "data science",
            "મશીન લર્નિંગ",
            "मशीन लर्निंग"
        ]
    },
    {
        "num": 27,
        "id": "computer_vision_services",
        "title": "Computer Vision Services",
        "category": "AI & Machine Learning",
        "url": "/computer-vision",
        "keywords": [
            "computer vision", "opencv", "image recognition", "object detection", "ocr",
            "video analytics", "facial recognition", "defect detection", "visual ai",
            "કમ્પ્યુટર વિઝન",
            "कंप्यूटर विज़न"
        ]
    },
    {
        "num": 28,
        "id": "ai_automation_services",
        "title": "AI Automation & Workflow Services",
        "category": "AI & Machine Learning",
        "url": "/ai-automation",
        "keywords": [
            "ai automation", "workflow automation", "intelligent automation", "rpa",
            "document processing", "email automation", "zapier", "make",
            "એઆઇ ઓટોમેશન",
            "एआई ऑटोमेशन"
        ]
    },
    {
        "num": 29,
        "id": "mlops_services",
        "title": "MLOps & AI Infrastructure Services",
        "category": "AI & Machine Learning",
        "url": "/mlops",
        "keywords": [
            "mlops", "model deployment", "model monitoring", "ai infrastructure",
            "kubernetes", "docker", "ci/cd for ml", "model optimization", "lifecycle management",
            "એમએલઓપ્સ",
            "एमएलऑप्स"
        ]
    },
    {
        "num": 30,
        "id": "ar_development_services",
        "title": "AR (Augmented Reality) Development Services",
        "category": "Immersive Technology",
        "url": "/ar, /augmented-reality",
        "keywords": [
            "ar", "augmented reality", "arkit", "arcore", "webar", "8thwall",
            "interactive 3d", "spatial computing", "ar try-on", "augmented",
            "એઆર", "ઓગમેન્ટેડ રિયાલિટી",
            "एआर", "ऑगमेंटेड रियलिटी"
        ]
    },
    {
        "num": 31,
        "id": "vr_development_services",
        "title": "VR (Virtual Reality) Development Services",
        "category": "Immersive Technology",
        "url": "/vr",
        "keywords": [
            "vr", "virtual reality", "oculus", "meta quest", "unity vr", "unreal engine vr",
            "vr training", "virtual simulations", "virtual tour", "headset",
            "વીઆર", "વર્ચ્યુઅલ રિયાલિટી",
            "वीआर", "वर्चुअल रियलिटी"
        ]
    },
    {
        "num": 32,
        "id": "mr_mixed_reality_solutions",
        "title": "MR (Mixed Reality) Solutions",
        "category": "Immersive Technology",
        "url": "/mr",
        "keywords": [
            "mr", "mixed reality", "mrtk", "magic leap", "spatial anchors",
            "interactive spatial", "spatial ui", "holographic",
            "મિશ્રિત વાસ્તવિકતા",
            "मिश्रित वास्तविकता"
        ]
    },
    {
        "num": 33,
        "id": "xr_extended_reality_solutions",
        "title": "XR (Extended Reality) Solutions",
        "category": "Immersive Technology",
        "url": "/xr",
        "keywords": [
            "xr", "extended reality", "spatial computing", "webxr", "immersive environments",
            "cross-platform xr", "xr experiences",
            "એક્સઆર",
            "एक्सआर"
        ]
    },
    {
        "num": 34,
        "id": "metaverse_solutions",
        "title": "Metaverse Solutions & Virtual Worlds",
        "category": "Immersive Technology",
        "url": "/metaverse",
        "keywords": [
            "metaverse", "virtual world", "virtual spaces", "decentraland", "sandbox",
            "spatial.io", "webgl", "three.js", "virtual events", "3d avatars",
            "મેટાવર્સ", "વર્ચ્યુઅલ વર્લ્ડ",
            "मेटावर्स", "वर्चुअल दुनिया"
        ]
    },
    {
        "num": 35,
        "id": "immersive_services",
        "title": "Immersive Technology Services (Overview)",
        "category": "Immersive Technology",
        "url": "/serviceimmersive",
        "keywords": [
            "immersive services", "immersive technology", "interactive digital",
            "ઇમર્સિવ સેવાઓ", "इमर्सिव सेवाएं"
        ]
    },
    {
        "num": 36,
        "id": "android_game_development",
        "title": "Android Game Development Services",
        "category": "Games & Web3",
        "url": "/android-games",
        "keywords": [
            "android games", "mobile games", "game development", "unity game",
            "unreal game", "google play console", "multiplayer game", "gdd",
            "એન્ડ્રોઇડ ગેમ્સ",
            "एंड्रॉयड गेम्स"
        ]
    },
    {
        "num": 37,
        "id": "ios_game_development",
        "title": "iOS Game Development Services",
        "category": "Games & Web3",
        "url": "/ios-games",
        "keywords": [
            "ios games", "apple games", "iphone games", "ipad games", "spritekit",
            "scenekit", "metal", "app store games", "game center",
            "આઇઓએસ ગેમ્સ",
            "आईओएस गेम्स"
        ]
    },
    {
        "num": 38,
        "id": "metaverse_games_development",
        "title": "Metaverse Games Development",
        "category": "Games & Web3",
        "url": "/metaverse-games",
        "keywords": [
            "metaverse game", "virtual world game", "3d game", "blockchain game",
            "decentralized game", "virtual environment game",
            "મેટાવર્સ ગેમ્સ",
            "मेटावर्स गेम्स"
        ]
    },
    {
        "num": 39,
        "id": "nft_game_development",
        "title": "NFT Game Development",
        "category": "Games & Web3",
        "url": "/nft-games",
        "keywords": [
            "nft game", "play to earn", "web3 game", "crypto game", "smart contracts",
            "digital assets game", "erc-721", "erc-1155",
            "એનએફટી ગેમ",
            "एनएफटी गेम"
        ]
    },
    {
        "num": 40,
        "id": "nft_marketplace_development",
        "title": "NFT Marketplace Development",
        "category": "Games & Web3",
        "url": "/nft-marketplace",
        "keywords": [
            "nft marketplace", "nft platform", "opensea clone", "minting",
            "smart contracts", "solana", "ethereum", "polygon", "web3", "digital collectibles",
            "એનએફટી માર્કેટપ્લેસ",
            "एनएफटी मार्केटप्लेस"
        ]
    }
]


PDF_SERVICE_NAMES = {
    1: "Brand Identity Design",
    2: "Graphic / UI-UX Design",
    3: "2D & 3D Animation",
    4: "CGI & Video Production",
    5: "3D Modeling",
    6: "Website Redesign",
    7: "Web Development",
    8: "Mobile App Development",
    9: "Software Development",
    10: "Custom Development",
    11: "Low-Code Development",
    12: "SaaS Development",
    13: "Shopify Development",
    14: "WordPress Development",
    15: "Technology Migration",
    16: "ERP Solutions",
    17: "ERP Development",
    18: "CRM Development",
    19: "Digital Marketing",
    20: "SEO",
    21: "Immersive Marketing",
    22: "AI Development",
    23: "Generative AI",
    24: "AI Agents",
    25: "RAG AI",
    26: "Machine Learning",
    27: "Computer Vision",
    28: "AI Automation",
    29: "MLOps",
    30: "AR Development",
    31: "VR Development",
    32: "MR (Mixed Reality)",
    33: "XR (Extended Reality)",
    34: "Metaverse Solutions",
    35: "Immersive Services",
    36: "Android Game Development",
    37: "iOS Game Development",
    38: "Metaverse Game Development",
    39: "NFT Game Development",
    40: "NFT Marketplace Development",
}


def extract_services_from_pdf(pdf_path: Path) -> Dict[int, str]:
    """
    Extract exact text sections for each service 1..40 from the PDF.
    Uses clean regex heading boundary matching with exact service names.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")

    reader = pypdf.PdfReader(str(pdf_path))
    pages_text = [p.extract_text() or "" for p in reader.pages]
    full_text = "\n".join(pages_text)

    found_positions = []
    for num, name in PDF_SERVICE_NAMES.items():
        escaped_name = re.escape(name)
        regex = rf'(?m)^{num}\.\s+{escaped_name}'
        matches = list(re.finditer(regex, full_text))
        if matches:
            # Pick the match in the document body (past page 6 table of contents)
            body_matches = [m for m in matches if m.start() > 5000]
            chosen = body_matches[0] if body_matches else matches[-1]
            found_positions.append((num, chosen.start()))
        else:
            print(f"[WARN] Header for #{num} ({name}) not found with strict regex")

    found_positions.sort(key=lambda x: x[1])

    extracted = {}
    for i in range(len(found_positions)):
        num, start_pos = found_positions[i]
        if i + 1 < len(found_positions):
            end_pos = found_positions[i+1][1]
        else:
            wlb_idx = full_text.find("Work-Life Balance", start_pos)
            end_pos = wlb_idx if wlb_idx != -1 else len(full_text)
        service_text = full_text[start_pos:end_pos].strip()
        extracted[num] = service_text

    return extracted


def build_knowledge_base():
    print(f"Reading from {PDF_PATH}...")
    service_texts = extract_services_from_pdf(PDF_PATH)
    print(f"Extracted {len(service_texts)} service sections from PDF.")

    # Canonical Company Identity Chunk
    company_chunk = {
        "id": "company_identity_and_contact",
        "title": "Company Identity, Location & Contact Details",
        "category": "Corporate",
        "url": "https://we3vision.com/contact",
        "keywords": [
            "company", "who is we3vision", "about we3vision", "contact", "location", "address",
            "phone", "email", "headquarters", "surat", "germany", "marburg", "hr", "cin",
            "founded", "director", "directors", "parth patel", "vinod patel", "mohit patel",
            "harsh ramoliya", "leadership", "coo", "cfo", "md", "founder", "office",
            "social media", "instagram", "linkedin", "team size",
            "કંપની", "સ્થળ", "સરનામું", "ફોન", "સંપર્ક", "ઈમેલ", "સુરત", "જર્મની", "ક્યાં", "ઓફિસ",
            "ડાયરેક્ટર", "ડિરેક્ટર", "ડાયરેકટર", "ડિરેકટર", "પાર્થ પટેલ", "વિનોદ પટેલ", "મોહિત પટેલ", "હર્ષ રામોલિયા",
            "વી3વિઝન", "વે3વિઝન", "વીથ્રીવિઝન", "લીડરશીપ",
            "पता", "कहाँ", "संपर्क", "फ़ोन", "कंपनी", "ईमेल", "सूरत", "कार्यालय", "डायरेक्टर", "लीडरशिप"
        ],
        "content": (
            "Company Name: We3vision Private Limited\n"
            "Corporate Identity Number (CIN): U72900GJ2022PTC132204\n"
            "Registration Date: 20 May 2022\n"
            "Founded: 2019\n"
            "Company Size: 11–50 Employees\n"
            "Official Email: info@we3vision.com\n"
            "Careers & HR Email: hr@we3vision.com\n"
            "Phone: +91 7383216096 / +91 7600772240 / +91 9328905389\n"
            "Official Website: https://we3vision.com (www.we3vision.com)\n\n"
            "Social Media Profiles:\n"
            "- Instagram: https://www.instagram.com/we3vision_private_limited/\n"
            "- LinkedIn: https://in.linkedin.com/company/we3visionprivatelimited\n\n"
            "Offices & Locations:\n"
            "1. Head Office & Headquarters (Surat, India):\n"
            "   We3vision House, 1/936 A, Bhim Kachchhi Mohallo, Nanpura, Surat, Gujarat, India 395001.\n"
            "2. Germany Office: Biegenstraße 18, 35037 Marburg, Germany.\n\n"
            "Leadership & Key Management:\n"
            "- Director & COO: Parth Patel\n"
            "- Board of Directors: Mohit Patel, Vinod Patel\n"
            "- Founder & Managing Director (MD): Harsh Ramoliya\n"
            "- Board of Directors (BOD) & CFO: Vinod Patel\n"
            "- Project Manager: Mohit Patel"
        )
    }

    # Careers, Culture & Work-Life Balance Chunk
    careers_chunk = {
        "id": "careers_culture_and_work_life",
        "title": "Careers, Job Openings, Culture & Work-Life Balance",
        "category": "Careers",
        "url": "https://we3vision.com/careers",
        "keywords": [
            "careers", "jobs", "internship", "hiring", "open roles", "culture", "work life balance",
            "remote work", "fresher", "graphic design intern", "apply", "hr", "benefits",
            "નોકરી", "કારકિર્દી", "ઇન્ટર્નશીપ", "નોકરીઓ",
            "करियर", "नौकरी", "इंटर्नशिप", "हायरिंग", "काम का माहौल"
        ],
        "content": (
            "Careers & Culture at We3vision Private Limited:\n\n"
            "Work-Life Balance & Culture:\n"
            "- Flexible timing, remote and hybrid work options, and mental wellness (we don't believe in burnout).\n"
            "- Celebrations & culture: Casual Fridays, virtual games, project success parties, and festival celebrations.\n"
            "- Supportive culture: Freedom to innovate, mentorship, and opportunities to grow into leadership roles.\n\n"
            "Open Roles & Internships:\n"
            "- Graphic Design Intern: Entry level, located at We3vision House, Surat. Freshers with a creative mindset and portfolio are welcome.\n"
            "- How to Apply: Send your resume to hr@we3vision.com.\n\n"
            "Frequently Asked Questions (Careers):\n"
            "- Can I work remotely? Yes, most roles offer flexible remote or hybrid options.\n"
            "- Do you hire interns or freshers? Absolutely, freshers and interns are mentored.\n"
            "- Work timings? Flexible hours focusing on delivery.\n"
            "- International projects? Yes, global client projects across the US, UK, UAE, and beyond."
        )
    }

    # Core Overview Chunk
    overview_chunk = {
        "id": "core_services_overview",
        "title": "We3Vision Complete Services Catalogue Overview (40 Services)",
        "category": "Overview",
        "url": "https://we3vision.com/services",
        "keywords": [
            "services", "what do you do", "offerings", "expertise", "portfolio",
            "web", "mobile", "ai", "metaverse", "ar", "vr", "3d", "gaming", "marketing", "erp", "crm",
            "40 services", "design", "development",
            "સેવાઓ", "શું કામ કરો છો", "ઓફરિંગ્સ",
            "सेवाएं", "क्या सेवाएं प्रदान करते हैं", "ऑफरिंग्स"
        ],
        "content": (
            "We3vision Private Limited provides 40 distinct services across 7 core categories:\n\n"
            "1. Design & Creative: Brand Identity Design (/brand-identity), Graphic / UI-UX Design (/graphics), "
            "2D & 3D Animation (/animation), CGI & Video Production (/cgi), 3D Modeling (/3d-modeling), "
            "Website Redesign (/redesign, /website-redesign).\n"
            "2. Web & Software Development: Web Development (/webdev), Mobile App Development (/mobile), "
            "Software Development (/software), Custom Development (/custom-dev), Low-Code Development (/low-code), "
            "SaaS Development (/Saas), Shopify Development (/shopify), WordPress Development (/wordpress), "
            "Technology Migration (/tech-migration).\n"
            "3. Enterprise Solutions: ERP Solutions (/erp-dev), ERP Development (/erp), CRM Development (/crm).\n"
            "4. Marketing: Digital Marketing (/marketing), Search Engine Optimization SEO (/seo), "
            "Immersive Marketing (/immersive-marketing).\n"
            "5. AI & Machine Learning: AI Development (/ai), Generative AI (/generative-ai), AI Agents (/ai-agents), "
            "Retrieval-Augmented Generation RAG AI (/rag-ai), Machine Learning (/machine-learning), "
            "Computer Vision (/computer-vision), AI Automation (/ai-automation), MLOps (/mlops).\n"
            "6. Immersive Technology: AR Development (/ar, /augmented-reality), VR Development (/vr), "
            "Mixed Reality MR (/mr), Extended Reality XR (/xr), Metaverse Solutions (/metaverse), "
            "Immersive Services (/serviceimmersive).\n"
            "7. Games & Web3: Android Game Development (/android-games), iOS Game Development (/ios-games), "
            "Metaverse Game Development (/metaverse-games), NFT Game Development (/nft-games), "
            "NFT Marketplace Development (/nft-marketplace)."
        )
    }

    # Featured Projects & Portfolio
    portfolio_chunk = {
        "id": "featured_projects_and_track_record",
        "title": "Featured Projects, Portfolio & Track Record",
        "category": "Portfolio",
        "url": "https://we3vision.com/portfolio",
        "keywords": [
            "projects", "portfolio", "case studies", "work", "clients", "track record",
            "coal mining", "jewellery", "virtual showroom", "ar try-on", "mining safety", "success stories",
            "પ્રોજેક્ટ", "પોર્ટફોલિયો", "કામ", "ગ્રાહકો",
            "प्रोजेक्ट्स", "पोर्टफोलियो", "केस स्टडीज", "क्लाइंट्स"
        ],
        "content": (
            "Notable We3Vision Client Implementations & Proof of Concepts:\n"
            "1. Coal Mining Safety VR Simulator: High-fidelity interactive VR safety training for hazardous "
            "underground mining environments. Replaced hazardous live drills with immersive simulations that reduced "
            "onboarding training risks.\n"
            "2. Luxury Jewellery AR Try-On: Real-time hand and wrist tracking WebAR/native experience for high-end "
            "jewellery brands, allowing customers to visualize rings, necklaces, and bracelets before purchasing.\n"
            "3. 3D WebGL Configurator for Industrial Equipment: Interactive 360-degree real-time 3D product "
            "customizer directly inside the browser without app installation, boosting customer sales conversions.\n"
            "4. Enterprise Technology Migration: Cloud transformation and database migration for mid-market "
            "retailers with zero customer downtime during checkout operations.\n"
            "5. Enterprise AI & Knowledge Retrieval: Custom RAG and Agentic systems designed for corporate document "
            "ingestion, compliance auditing, and conversational employee assistance."
        )
    }

    chunks = [company_chunk, overview_chunk, careers_chunk]

    # Add each extracted service chunk
    for meta in SERVICE_METADATA_DEFS:
        num = meta["num"]
        raw_content = service_texts.get(num, "")
        if not raw_content:
            print(f"[WARN] No extracted text for service #{num} ({meta['title']})")
            continue

        clean_content = f"Service #{num}: {meta['title']}\nCategory: {meta['category']}\nURL: {meta['url']}\n\n{raw_content}"
        chunks.append({
            "id": meta["id"],
            "title": meta["title"],
            "category": meta["category"],
            "url": meta["url"],
            "keywords": meta["keywords"],
            "content": clean_content
        })

    chunks.append(portfolio_chunk)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    print(f"Knowledge base successfully generated with {len(chunks)} chunks at:\n{JSON_OUTPUT_PATH}")


if __name__ == "__main__":
    build_knowledge_base()
