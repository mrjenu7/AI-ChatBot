import asyncio
import base64
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.services.tts_service import synthesize_speech_bundle

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str | None = None


async def _speech(request: TTSRequest) -> dict:
    try:
        return await asyncio.wait_for(synthesize_speech_bundle(request.text, request.language), timeout=40)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Speech generation timed out. Please retry.") from exc
    except Exception as exc:
        logger.warning("Speech generation failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Speech is unavailable. Check your internet connection and backend speech dependencies.",
        ) from exc


@router.post("/tts-sync")
async def synchronized_text_to_speech(request: TTSRequest):
    return JSONResponse(await _speech(request), headers={"Cache-Control": "no-store"})


@router.post("/tts")
async def text_to_speech(request: TTSRequest):
    bundle = await _speech(request)
    return Response(
        base64.b64decode(bundle["audio_base64"]),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Detected-Language": bundle["language"]},
    )
