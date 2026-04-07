"""Unified configuration loaded from environment variables / .env file."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DashScope AI
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.5-plus"

    # Innomate API
    innomate_api_url: str = ""

    # Data directories (resolved relative to project root at runtime)
    md_raw_dir: str = "../data/raw"
    md_redacted_dir: str = "../data/redacted"
    index_dir: str = "../data/index"

    # Auth
    secret_key: str = ""
    unified_password: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    def model_post_init(self, __context) -> None:
        """Validate critical security settings at startup."""
        if not self.secret_key or self.secret_key == "change-me-to-a-random-string":
            import secrets
            import warnings
            warnings.warn(
                "SECURITY WARNING: secret_key is not set. Using auto-generated key. "
                "This will invalidate all existing tokens on restart.",
                UserWarning,
            )
            self.secret_key = secrets.token_hex(32)
        if not self.unified_password:
            import warnings
            warnings.warn(
                "SECURITY WARNING: unified_password is not configured.",
                UserWarning,
            )

    # Dify Knowledge Base
    dify_api_key: str = ""
    dify_base_url: str = "https://api.dify.ai/v1"
    dify_dataset_id: str = ""
    dify_index_dataset_id: str = ""

    # Batch processing
    batch_concurrency: int = 3

    # Database
    database_url: str = "postgresql+psycopg2://appuser:apppassword@db:5432/ai_data_platform"

    # Prompts directory
    prompts_dir: str = str(Path(__file__).resolve().parent.parent / "prompts")

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the backend/ directory."""
        base = Path(__file__).resolve().parent.parent
        return (base / relative).resolve()


settings = Settings()
