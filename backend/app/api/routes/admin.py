"""Protected endpoints for managing company knowledge documents."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.rag_service import reload_knowledge_base
from app.core.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])
BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
KNOWLEDGE_PATH = DATA_DIR / "we3vision_knowledge_base.json"
MANIFEST_PATH = DATA_DIR / "admin_documents.json"
MAX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".doc", ".docx"}


class DeleteResponse(BaseModel):
    message: str
    filename: str


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = settings.admin_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin panel is not configured. Set ADMIN_API_TOKEN on the backend.")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    # Compare without leaking whether a partial token matched.
    import hmac
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _extract_text(filename: str, payload: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        try:
            return payload.decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return payload.decode("latin-1").strip()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(payload))
            if getattr(reader, "is_encrypted", False):
                raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported.")
            return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not read this PDF: {exc}") from exc
    if ext == ".docx":
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(payload))
            parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(parts).strip()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not read this DOCX: {exc}") from exc
    if ext == ".doc":
        # Legacy Word files are parsed with antiword or LibreOffice when installed on the host.
        antiword = shutil.which("antiword")
        if antiword:
            try:
                result = subprocess.run([antiword, "-"], input=payload, capture_output=True, check=True, timeout=20)
                return result.stdout.decode("utf-8", errors="replace").strip()
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Could not read this DOC file: {exc}") from exc
        libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
        if libreoffice:
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                source = Path(tmpdir) / "upload.doc"
                source.write_bytes(payload)
                try:
                    subprocess.run([libreoffice, "--headless", "--convert-to", "txt:Text", "--outdir", tmpdir, str(source)], capture_output=True, check=True, timeout=30)
                    converted = Path(tmpdir) / "upload.txt"
                    if converted.exists():
                        return converted.read_text(encoding="utf-8", errors="replace").strip()
                except Exception as exc:
                    raise HTTPException(status_code=422, detail=f"Could not convert this DOC file: {exc}") from exc
        raise HTTPException(status_code=415, detail="Legacy .doc requires antiword or LibreOffice on the backend host. Alternatively, save it as .docx or PDF and upload again.")
    raise HTTPException(status_code=415, detail="Supported formats are PDF, TXT, and DOCX. Legacy DOC files require conversion to DOCX or PDF.")


def _keywords(text: str, filename: str) -> list[str]:
    tokens = re.findall(r"[\w\u0A80-\u0AFF\u0900-\u097F]{3,}", text.lower())
    unique = list(dict.fromkeys(tokens))[:100]
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip().lower()
    if stem and stem not in unique:
        unique.insert(0, stem)
    return unique[:100]


def _split_chunks(text: str, filename: str, digest: str) -> list[dict[str, Any]]:
    # Keep chunk size compatible with the current keyword-based RAG retrieval.
    chunk_size, overlap = 1400, 180
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        content = text[start:end].strip()
        if content:
            chunks.append({
                "id": f"uploaded_{digest[:12]}_{len(chunks) + 1}",
                "title": f"{Path(filename).stem} (Part {len(chunks) + 1})",
                "category": "Admin Uploaded Document",
                "url": "",
                "keywords": _keywords(content, filename),
                "content": content,
                "source_document": filename,
                "source_hash": digest,
            })
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _manifest() -> list[dict[str, Any]]:
    return _read_json(MANIFEST_PATH, [])


@router.get("/health", dependencies=[Depends(require_admin)])
def admin_health() -> dict[str, str]:
    return {"status": "ok", "message": "Admin API is ready."}


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents() -> dict[str, Any]:
    documents = _manifest()
    return {"documents": sorted(documents, key=lambda item: item.get("uploaded_at", ""), reverse=True), "count": len(documents)}


@router.post("/documents", dependencies=[Depends(require_admin)])
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    raw_name = Path(file.filename or "upload").name
    ext = Path(raw_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported file extensions: .pdf, .txt, .docx. Legacy .doc is not currently parseable.")
    payload = await file.read(MAX_FILE_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Maximum upload size is 15 MB.")
    text = _extract_text(raw_name, payload)
    if len(text.strip()) < 20:
        raise HTTPException(status_code=422, detail="No usable text was found. Scanned PDFs need OCR before upload.")

    digest = hashlib.sha256(payload).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", raw_name).strip(" .") or f"document{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Stored under a hash-based filename to avoid path traversal and filename collisions.
    stored_path = UPLOAD_DIR / f"{digest[:16]}_{safe_name}"
    stored_path.write_bytes(payload)

    current_chunks = _read_json(KNOWLEDGE_PATH, [])
    if not isinstance(current_chunks, list):
        raise HTTPException(status_code=500, detail="Knowledge base JSON must contain a list of chunks.")
    # Uploading the same filename updates that document's previous chunks; all other knowledge remains.
    retained = [chunk for chunk in current_chunks if chunk.get("source_document") != safe_name]
    new_chunks = _split_chunks(text, safe_name, digest)
    if not new_chunks:
        raise HTTPException(status_code=422, detail="The document did not produce any searchable text chunks.")
    _atomic_json_write(KNOWLEDGE_PATH, retained + new_chunks)

    old_documents = _manifest()
    old_match = next((item for item in old_documents if item.get("filename") == safe_name), None)
    documents = [item for item in old_documents if item.get("filename") != safe_name]
    documents.append({
        "filename": safe_name,
        "stored_name": stored_path.name,
        "sha256": digest,
        "size_bytes": len(payload),
        "chunks": len(new_chunks),
        "characters": len(text),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "status": "processed",
    })
    _atomic_json_write(MANIFEST_PATH, documents)
    if old_match and old_match.get("stored_name") and old_match.get("stored_name") != stored_path.name:
        try:
            (UPLOAD_DIR / Path(old_match["stored_name"]).name).unlink(missing_ok=True)
        except OSError:
            pass
    reload_knowledge_base()
    return {"message": "Document processed and knowledge base updated.", "document": documents[-1]}


@router.delete("/documents/{filename}", response_model=DeleteResponse, dependencies=[Depends(require_admin)])
def delete_document(filename: str) -> DeleteResponse:
    documents = _manifest()
    match = next((item for item in documents if item.get("filename") == filename), None)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found in the admin-managed uploads.")
    chunks = _read_json(KNOWLEDGE_PATH, [])
    _atomic_json_write(KNOWLEDGE_PATH, [chunk for chunk in chunks if chunk.get("source_document") != filename])
    _atomic_json_write(MANIFEST_PATH, [item for item in documents if item.get("filename") != filename])
    stored_name = match.get("stored_name")
    if stored_name:
        try:
            (UPLOAD_DIR / Path(stored_name).name).unlink(missing_ok=True)
        except OSError:
            pass
    reload_knowledge_base()
    return DeleteResponse(message="Document deleted and knowledge base refreshed.", filename=filename)
