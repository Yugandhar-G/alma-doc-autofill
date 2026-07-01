"""Central configuration. Every tunable lives here or in the environment —
nothing is hardcoded at call sites."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Vision extraction
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash"          # default tier; Agent A verifies current id
    gemini_model_escalation: str = "gemini-3-pro" # used when default returns null-heavy result
    extraction_temperature: float = 0.0
    extraction_max_retries: int = 1

    # Storage (Supabase when set, local disk otherwise)
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_bucket: str = "documents"
    local_storage_dir: str = "uploads"

    # Upload guardrails
    max_file_mb: int = 10
    max_pdf_pages: int = 10
    allowed_formats: tuple[str, ...] = ("pdf", "jpeg", "png")
    min_image_dimension: int = 500        # px, shorter side
    blur_threshold: float = 40.0          # variance of Laplacian below this → reject

    # PDF rendering
    render_dpi: int = 220

    # Population
    target_form_url: str = "https://mendrika-alma.github.io/form-submission/"
    populate_headed: bool = True
    populate_timeout_ms: int = 60_000

    # Frontend origin for CORS
    frontend_origin: str = "http://localhost:3000"

    def require_gemini_key(self) -> str:
        if not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to backend/.env and add your key."
            )
        return self.gemini_api_key

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
