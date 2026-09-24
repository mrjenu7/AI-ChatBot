#!/usr/bin/env python3
"""
genrate_pdf.py
Script to generate / ensure the 179-page PDF knowledge base exists at:
backend/data/we3vision_knowledge_base.pdf
"""

import shutil
import sys
from pathlib import Path

try:
    import pypdf
except ImportError:
    pypdf = None

CURRENT_DIR = Path(__file__).resolve().parent
if CURRENT_DIR.name == "services":
    BACKEND_DIR = CURRENT_DIR.parent.parent
elif CURRENT_DIR.name == "backend":
    BACKEND_DIR = CURRENT_DIR
else:
    BACKEND_DIR = CURRENT_DIR / "backend"

DATA_DIR = BACKEND_DIR / "data"
PDF_TARGET = DATA_DIR / "we3vision_knowledge_base.pdf"
UPLOADED_SOURCES = [
    Path("/Users/milisheta/Desktop/We3vision Private Limited (1).pdf"),
    Path("/Users/milisheta/we3vision/AI_chatbot_all_version/We3vision Private Limited.pdf"),
]


def generate_or_verify_pdf():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Find the newest existing source PDF
    valid_sources = [p for p in UPLOADED_SOURCES if p.exists()]
    if valid_sources:
        source_pdf = max(valid_sources, key=lambda p: p.stat().st_mtime)
        print(f"Syncing uploaded PDF from {source_pdf} to {PDF_TARGET}...")
        shutil.copy2(source_pdf, PDF_TARGET)
        # Also sync to parent folder copy if different
        parent_copy = Path("/Users/milisheta/we3vision/AI_chatbot_all_version/We3vision Private Limited.pdf")
        if source_pdf != parent_copy:
            try:
                shutil.copy2(source_pdf, parent_copy)
            except Exception:
                pass
        print("Copy completed successfully.")
    elif not PDF_TARGET.exists():
        print(f"[ERROR] Source PDF not found in {UPLOADED_SOURCES} and target does not exist at {PDF_TARGET}")
        sys.exit(1)

    if pypdf is not None and PDF_TARGET.exists():
        reader = pypdf.PdfReader(str(PDF_TARGET))
        print(f"Verified PDF at {PDF_TARGET}: {len(reader.pages)} pages.")
    else:
        print(f"PDF ready at {PDF_TARGET}")


if __name__ == "__main__":
    generate_or_verify_pdf()
