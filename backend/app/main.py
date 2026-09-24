from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.chat import router as chat_router
from app.api.routes.voice import router as voice_router
from app.core.config import settings


app = FastAPI(
    title="We3vision AI Business Agent",
    description="Backend API for We3vision AI Business Agent",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router, prefix="/api")
app.include_router(voice_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "We3vision AI Business Agent API is running"}
