"""Application configuration.

Only application-level, runtime-level, and AI-level configuration is stored in
environment variables. Project and integration configuration live in the
application database.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPOSITORY_ROOT / "data"
_WORKSPACE_DIR = _DATA_DIR / "workspaces"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: str = "api-doctor-dev-secret"
    DATABASE_URL: str = "sqlite:///./data/api_doctor.db"

    # ------------------------------------------------------------------
    # Operational Mode
    # ------------------------------------------------------------------
    DEMO_MODE: bool = False

    # ------------------------------------------------------------------
    # NVIDIA NIM (initial AI provider)
    # ------------------------------------------------------------------
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    INVESTIGATOR_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
    CODER_MODEL: str = "z-ai/glm-5.2"
    FAST_MODEL: str = "nvidia/nemotron-3-nano-30b-a3b"
    EMBEDDING_MODEL: str = "nvidia/nv-embedcode-7b-v1"

    # ------------------------------------------------------------------
    # GitHub / Render API defaults (non-secret, non-project-specific)
    # ------------------------------------------------------------------
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    RENDER_API_BASE_URL: str = "https://api.render.com/v1"

    # ------------------------------------------------------------------
    # AI behaviour
    # ------------------------------------------------------------------
    AI_PROVIDER: str = "auto"
    AI_TIMEOUT_SECONDS: float = 90.0
    AI_REQUEST_TIMEOUT_SECONDS: float = 35.0
    AI_MAX_TOKENS: int = 4096
    AI_MAX_RETRIES: int = 3
    AI_TEMPERATURE: float = 0.1
    AI_MODEL_FALLBACK: bool = True

    # ------------------------------------------------------------------
    # AI cache
    # ------------------------------------------------------------------
    AI_CACHE_ENABLED: bool = True
    AI_CACHE_TTL_SECONDS: int = 3600
    AI_CACHE_MAX_SIZE: int = 128
    AI_CACHE_SEMANTIC_ENABLED: bool = False
    AI_CACHE_SEMANTIC_THRESHOLD: float = 0.9

    # ------------------------------------------------------------------
    # Sandbox
    # ------------------------------------------------------------------
    SANDBOX_MODE: str = "local"
    SANDBOX_BASE_IMAGE: str = "python:3.11-slim"
    SANDBOX_TIMEOUT_SECONDS: int = 120
    SANDBOX_MEMORY_LIMIT: str = "512m"
    SANDBOX_NETWORK_ENABLED: bool = False

    # ------------------------------------------------------------------
    # Repair limits
    # ------------------------------------------------------------------
    MAX_REPAIR_ATTEMPTS: int = 2

    # ------------------------------------------------------------------
    # Code retrieval
    # ------------------------------------------------------------------
    MAX_CONTEXT_FILES: int = 4
    CODE_RETRIEVAL_TOP_K: int = 5
    CONTEXT_LINE_WINDOW: int = 12

    # ------------------------------------------------------------------
    # Workflow gates
    # ------------------------------------------------------------------
    REQUIRE_SANDBOX: bool = True
    REQUIRE_TESTS: bool = True
    REQUIRE_VERIFICATION: bool = True
    AUTO_CREATE_PR: bool = False
    AUTO_MERGE: bool = False
    MIN_ROOT_CAUSE_CONFIDENCE: float = 0.6

    # ------------------------------------------------------------------
    # Internal paths
    # ------------------------------------------------------------------
    REPOSITORY_ROOT: str = str(_REPOSITORY_ROOT)
    BACKEND_ROOT: str = str(_BACKEND_ROOT)
    DATA_DIR: str = str(_DATA_DIR)
    WORKSPACE_DIR: str = str(_WORKSPACE_DIR)
    INTERNAL_REPO_ROOT: str = str(_BACKEND_ROOT)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    HTTP_TIMEOUT_SECONDS: float = 15.0

    @property
    def has_nvidia(self) -> bool:
        return bool(self.NVIDIA_API_KEY)

    def secret_scan_patterns(self) -> list[str]:
        return [
            "nvidia_api_key",
            "github_token",
            "render_api_key",
            "openai_api_key",
            "anthropic_api_key",
            "secret_key",
            "database_url",
            "postgres",
            "mysql",
            "redis",
            "password",
            "secret",
            "token",
            "apikey",
            "api_key",
            "authorization",
            "cookie",
            "jwt",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
