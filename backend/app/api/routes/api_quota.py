"""Report honest local provider usage; vendor-wide billing quota is not inferred."""
import os
from pathlib import Path
from dotenv import dotenv_values
from fastapi import APIRouter, Depends
from app.api.routes.admin import require_admin
from app.core.config import ENV_FILE

router = APIRouter(prefix="/api/admin", tags=["admin-quota"])

def _configuration():
    values = dict(dotenv_values(ENV_FILE)) if Path(ENV_FILE).is_file() else {}
    # Environment variables override the .env file.
    values.update(os.environ)
    return values

@router.get("/api-quotas", dependencies=[Depends(require_admin)])
def get_quotas():
    values = _configuration()
    def record(name, keys, limit_key):
        configured = any(bool(str(values.get(k) or '').strip()) and
                         not str(values.get(k)).lower().startswith('your_') for k in keys)
        raw_limit = str(values.get(limit_key) or '')
        limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else None
        return {"name": name, "configured": configured,
                "used": None, "limit": limit, "used_percent": None,
                "remaining_percent": None, "source": "configuration only",
                "status": "Key detected; provider-wide usage requires billing/usage API access" if configured
                          else "No matching API key in backend/.env or environment"}
    return {"providers": [
        record("ABSTRACT_API", ["ABSTRACT_API"], "ABSTRACT_API_LIMIT"),
        record("Gemini API", ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"], "GEMINI_API_LIMIT")],
        "note": "Credential detection is live from backend/.env. Provider quota percentages are not available through these credentials alone."}
