"""Automatically assemble extracted website pages into one readable PDF."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def build_website_pdf(destination: Path, pages: list, documents: list):
    destination.parent.mkdir(parents=True, exist_ok=True)
    font = "Helvetica"
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(candidate).exists():
            pdfmetrics.registerFont(TTFont("WebsiteUnicode", candidate))
            font = "WebsiteUnicode"
            break
    styles = getSampleStyleSheet()
    heading = ParagraphStyle("WebHeading", parent=styles["Heading2"], fontName=font, fontSize=13, leading=18, spaceAfter=8)
    body = ParagraphStyle("WebBody", fontName=font, fontSize=9, leading=13, spaceAfter=5, wordWrap="CJK")
    meta = ParagraphStyle("WebMeta", parent=body, textColor=colors.grey, fontSize=8)
    story = [Paragraph("Website Extraction Report", heading), Paragraph(f"{len(pages)} unique website pages and {len(documents)} documents", body), Spacer(1, 12)]
    entries = [(p.get("title") or p.get("url"), p.get("url"), p.get("original_text", "")) for p in pages]
    entries += [(d.get("filename") or d.get("url"), d.get("url"), d.get("original_text", "")) for d in documents]
    for i, (title, url, content) in enumerate(entries):
        if i: story.append(PageBreak())
        story.append(Paragraph(escape(str(title or "Untitled")), heading))
        story.append(Paragraph(escape(str(url or "")), meta))
        for paragraph in str(content or "No extractable text").splitlines():
            paragraph = paragraph.strip()
            if paragraph:
                # Break long text into safe chunks to avoid oversized reportlab paragraphs.
                for start in range(0, len(paragraph), 700):
                    story.append(Paragraph(escape(paragraph[start:start+700]), body))
    SimpleDocTemplate(str(destination), pagesize=A4, rightMargin=40, leftMargin=40, topMargin=44, bottomMargin=44).build(story)
    return destination
