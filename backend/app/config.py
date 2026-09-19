"""Application configuration, loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required -- the app will refuse to start without these.
    database_url: str
    supabase_url: str  # e.g. https://your-project-ref.supabase.co
    supabase_publishable_key: str  # Settings -> API Keys -> anon/publishable key
    gemini_api_key: str

    gemini_chat_model: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_transcribe_model: str = "gemini-3.5-transcribe"
    gemini_image_model: str = "gemini-3.1-flash-image-preview"
    gemini_tts_model: str = "gemini-3.1-flash-tts-preview"
    embedding_dimensions: int = 768

    environment: str = "development"
    cors_origins: str = "http://localhost:5173"
    # Fallback only, used when a save request doesn't include its own
    # timezone (see SaveItemRequest.timezone). Deliberately UTC, not any
    # specific region -- this app has no fixed home location, so "today"
    # should come from whoever is actually using it, not a hardcoded place.
    default_timezone: str = "UTC"

    max_items_per_user_per_day: int = 50
    max_chat_messages_per_user_per_day: int = 100

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance -- environment variables are read once per process."""
    return Settings()
