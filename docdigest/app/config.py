"""Application settings loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Voyage AI ---
    voyage_api_key: str = ""
    
    # --- Anthropic ---
    anthropic_api_key: str = ""

    """Global application settings.

    All values can be overridden via environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://postgres:password@localhost:5432/docdigest"
    )

    @property
    def async_database_url(self) -> str:
        """Return database URL with asyncpg driver, correcting Railway's scheme."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # --- File storage ---
    upload_dir: Path = Path("./uploads")

    # --- Chunking ---
    chunk_target_tokens: int = 1000
    chunk_overlap_tokens: int = 100

    # --- LLM models ---
    summary_model: str = "claude-sonnet-4-20250514"
    synthesis_model: str = "claude-opus-4-20250514"

    # --- Embeddings ---
    embedding_model: str = "voyage-3"

    # --- Q&A ---
    qa_top_k: int = 5

    # --- CORS ---
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Optional ---
    tesseract_cmd: str | None = None

    def ensure_upload_dir(self) -> Path:
        """Create upload directory if it doesn't exist."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        return self.upload_dir


settings = Settings()
