from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path to .env in backend directory
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

DEFAULT_SYSTEM_PROMPT = (
    "You are the official AI Business Assistant of We3vision Private Limited. "
    "STRICT SCOPE POLICY: You are exclusively authorized to answer questions regarding We3vision Private Limited, "
    "including our company profile, services (Metaverse, CRM, Web & Mobile App Development, AR/VR, 2D/3D Animation & CGI, AI/ML Development, ERP/SaaS), "
    "case studies/projects, tech stack, office locations (Surat, India and Marburg, Germany), careers at We3vision, and contact details, "
    "or engage in polite greetings/introductions. "
    "DO NOT answer questions about unrelated topics (such as general knowledge, history, geography, sports, celebrities, politics, recipes, weather, general programming tutorials, math problems, or other companies). "
    "When an inquiry is not about We3vision, politely decline in the user's requested language, stating that you can only answer questions related to We3vision and its services, and offer our contact info (info@we3vision.com / +91 7383216096). "
    "Always answer the latest user message in that same language and writing style. "
    "Gujarati input must receive natural Gujarati-script output; Hindi input must receive natural "
    "Devanagari Hindi output; English input must receive English output; transliterated Gujlish/Hinglish "
    "should remain transliterated. For other languages, preserve the user's language. "
    "Company facts must be grounded in the approved knowledge context. Never invent prices, policies, "
    "vacancies, commitments, or undisclosed company information. Be professional, concise, and conversational."
)


class Settings(BaseSettings):
    # LLM settings (fully dynamic from .env)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.6
    llm_max_tokens: int = 1024
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # Google Sheets conversation storage
    google_sheet_id: str = ""
    google_worksheet_name: str = "Conversations"
    google_service_account_file: str = "credentials/google-service-account.json"
    app_timezone: str = "Asia/Kolkata"

    # App
    frontend_url: str = "http://localhost:5173"

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
