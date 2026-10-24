"""Admin API for background website-to-JSON ingestion."""
from __future__ import annotations
import os, re, uuid, threading, json, shutil, tempfile
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app.api.routes.admin import require_admin
from app.services.website_ingestion_service import run_crawl
from app.services.website_ingestion_service import DATA_DIR as WEBSITE_DIR
from app.core.config import ENV_FILE
from dotenv import dotenv_values

router = APIRouter(prefix="/api/admin/website-ingestion", tags=["website-ingestion"])
_JOBS = {}
_LOCK = threading.RLock()
class WebsiteIngestionRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    include_documents: bool = True
    include_subdomains: bool = False
    model: str = "gemini-2.5-flash"

def update_job(job_id: str, fields: dict):
    with _LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)

@router.post("", dependencies=[Depends(require_admin)])
def start_ingestion(payload: WebsiteIngestionRequest, background_tasks: BackgroundTasks):
    parsed = urlparse(payload.url.strip())
    if parsed.scheme not in ("http","https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Enter a valid website URL beginning with https://")
    # Key in .env was previously ignored unless exported into process environment.
    file_keys = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
    api_key = (os.getenv("ABSTRACT_API") or file_keys.get("ABSTRACT_API") or
               os.getenv("GEMINI_API_KEY") or file_keys.get("GEMINI_API_KEY") or "").strip()
    if payload.model not in {"gemini-2.5-flash", "gemini-2.0-flash"}:
        raise HTTPException(status_code=422, detail="Model must be gemini-2.5-flash or gemini-2.0-flash.")
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {"job_id":job_id,"status":"queued","root_url":payload.url,
                         "discovered_urls":0,"processed_pages":0,"processed_documents":0,"failed_urls":[]}
    background_tasks.add_task(run_crawl, job_id, payload.url.strip(), api_key, payload.model,
                              payload.include_documents, payload.include_subdomains)
    return {"job_id":job_id,"status":"queued","message":"Website scan started. Raw JSON extraction does not require Gemini; structured facts are added when ABSTRACT_API is configured."}

# Static routes are declared before parameterized routes.
def _latest_dir():
    return WEBSITE_DIR / "latest"

@router.get("/latest", dependencies=[Depends(require_admin)])
def latest_extraction():
    report_path = _latest_dir() / "crawl_report.json"
    if not report_path.is_file():
        return {"available": False}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {"available": True, "job_id": report.get("job_id"),
            "status": report.get("status"), "approved": report.get("approved", False),
            "pdf_ready": (_latest_dir() / "website_extraction.pdf").is_file(),
            "pages": report.get("processed_pages", 0),
            "website": report.get("root_url", "")}

@router.get("/latest/pdf", dependencies=[Depends(require_admin)])
def get_latest_website_pdf(download: bool = False):
    path = _latest_dir() / "website_extraction.pdf"
    if not path.is_file():
        raise HTTPException(404, "No generated website PDF found.")
    return FileResponse(path, media_type="application/pdf", filename="website_extraction.pdf",
                        content_disposition_type="attachment" if download else "inline")

@router.get("/{job_id}/pdf", dependencies=[Depends(require_admin)])
def get_extraction_pdf(job_id: str, download: bool = False):
    report_path = _latest_dir() / "crawl_report.json"
    if not report_path.is_file():
        raise HTTPException(404, "No extraction found")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("job_id") != job_id:
        raise HTTPException(404, "This extraction was replaced")
    return get_latest_website_pdf(download)

@router.post("/latest/approve", dependencies=[Depends(require_admin)])
def approve_latest_extraction(payload: dict):
    # Serialise approval and prevent stale browser tabs approving a different crawl.
    with _LOCK:
        folder = _latest_dir()
        report_path = folder / "crawl_report.json"
        source_json = folder / "website_knowledge.json"
        source_pdf = folder / "website_extraction.pdf"
        if not all(x.is_file() for x in (report_path, source_json, source_pdf)):
            raise HTTPException(404, "PDF/JSON extraction files not found")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if payload.get("job_id") != report.get("job_id"):
            raise HTTPException(409, "A newer extraction exists. Refresh before approval.")
        if report.get("approved"):
            return {"message": "This extraction is already approved", "approved": True}
        master = json.loads(source_json.read_text(encoding="utf-8"))
        pages = master.get("pages", [])
        documents = master.get("documents", [])
        if not isinstance(pages, list) or not isinstance(documents, list) or not (pages or documents):
            raise HTTPException(422, "Extracted JSON has no usable pages or documents")
        from app.api.routes.admin import KNOWLEDGE_PATH, _keywords, _atomic_json_write
        from app.services.rag_service import reload_knowledge_base
        import hashlib
        chunks = []
        for item in pages + documents:
            content = str(item.get("original_text", "")).strip()
            if not content:
                continue
            source = item.get("url", "")
            title = item.get("title") or item.get("filename") or source
            digest = hashlib.sha256((source + content).encode()).hexdigest()[:14]
            for index, pos in enumerate(range(0, len(content), 1200)):
                segment = content[pos:pos+1400].strip()
                if segment:
                    chunks.append({"id": f"website_{digest}_{index}", "title": title,
                                   "category": "Website Knowledge", "url": source,
                                   "keywords": _keywords(segment, title), "content": segment,
                                   "source_document": source, "source_hash": digest})
        if not chunks:
            raise HTTPException(422, "Extraction contains no searchable text")
        active_pdf = KNOWLEDGE_PATH.with_suffix('.pdf')
        backup_dir = KNOWLEDGE_PATH.parent / 'knowledge_backups'
        backup_dir.mkdir(exist_ok=True)
        # Snapshot original files for rollback / manual recovery.
        for original in (KNOWLEDGE_PATH, active_pdf):
            if original.exists():
                shutil.copy2(original, backup_dir / (original.name + '.before_website_approval'))
        tmp_pdf = active_pdf.with_name('.approved_knowledge.tmp.pdf')
        shutil.copy2(source_pdf, tmp_pdf)
        try:
            _atomic_json_write(KNOWLEDGE_PATH, chunks)
            os.replace(tmp_pdf, active_pdf)
            reload_knowledge_base()
        except Exception as exc:
            for original in (KNOWLEDGE_PATH, active_pdf):
                backup = backup_dir / (original.name + '.before_website_approval')
                if backup.exists():
                    shutil.copy2(backup, original)
            reload_knowledge_base()
            raise HTTPException(500, f"Activation failed; previous files restored: {exc}")
        report['approved'] = True
        report['rag_chunks_added'] = len(chunks)
        from app.api.routes.admin import _atomic_json_write as write_json
        write_json(report_path, report)
        update_job(report['job_id'], {'approved': True, 'rag_chunks_added': len(chunks)})
        return {"approved": True, "chunks": len(chunks), "message": "Approved. Chatbot knowledge JSON and PDF replaced."}

@router.get("/{job_id}", dependencies=[Depends(require_admin)])
def get_ingestion_status(job_id: str):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found. Jobs are kept in memory until the backend restarts.")
        return dict(job)

