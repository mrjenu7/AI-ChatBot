from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path to .env in backend directory
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

DEFAULT_SYSTEM_PROMPT = (
    "You are We3vision Private Limited's official business assistant. Understand the user's input in any language, but always answer in English. "
    "Answer only about We3vision, its verified services, company information, portfolio, locations, careers, or contact details; politely decline unrelated requests. "
    "Use only the retrieved We3vision knowledge as evidence. Do not invent or infer services, features, technologies, results, prices, timelines, availability, or commitments. "
    "Keep each capability attached to the service whose source confirms it. Industry descriptions and portfolio examples do not prove every related feature is offered. "
    "If a detail is missing or marked unverified, say it needs confirmation and use only contact details present in the source. "
    "Answer the user's question directly in 2-4 concise sentences, ask at most one useful follow-up question, and use plain text without Markdown."
)


class Settings(BaseSettings):
    # LLM settings (fully dynamic from .env)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.6
    llm_max_tokens: int = 300
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # Google Sheets conversation storage
    google_sheet_id: str = ""
    google_worksheet_name: str = "Conversations"
    google_service_account_file: str = "credentials/google-service-account.json"
    #app_timezone: str = "Asia/Kolkata"

    # Supabase conversation storage
    supabase_url: str = ""
    supabase_service_key: str = ""
    
    app_timezone: str = "Asia/Kolkata"

    # App
    frontend_url: str = "http://localhost:5173"
    admin_api_token: str = ""
    admin_panel_origins: str = "http://localhost:4174,http://127.0.0.1:4174"

    @staticmethod
    def is_api_key_configured(value: str) -> bool:
        normalized = (value or "").strip().lower()
        return bool(normalized) and not normalized.startswith("your_") and normalized != "missing_key"

    @property
    def has_openai_api_key(self) -> bool:
        return self.is_api_key_configured(self.openai_api_key)

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
