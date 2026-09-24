from fastapi import APIRouter


router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "success": True,
        "message": "Backend is healthy",
    }
