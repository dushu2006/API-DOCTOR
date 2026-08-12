"""Application configuration.

All configuration values come from the environment (optionally a ``.env`` file).
Secrets are loaded here and are never exposed to the frontend, logs, or LLM
prompts (see :mod:`app.security.sanitizer`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # NVIDIA NIM (initial AI provider)
    # ------------------------------------------------------------------
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Model routing (exact names stay configurable — never hard-coded).
    # Faster defaults to cut latency; users may override in .env.
    INVESTIGATOR_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
    CODER_MODEL: str = "z-ai/glm-5.2"
    FAST_MODEL: str = "nvidia/nemotron-3-nano-30b-a3b"
    EMBEDDING_MODEL: str = "nvidia/nv-embedcode-7b-v1"

    # ------------------------------------------------------------------
    # GitHub integration
    # ------------------------------------------------------------------
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    GITHUB_TOKEN: str = ""
    GITHUB_OWNER: str = ""
    GITHUB_REPO: str = ""
    GITHUB_DEFAULT_BRANCH: str = "main"

    # ------------------------------------------------------------------
    # Render integration
    # ------------------------------------------------------------------
    RENDER_API_BASE_URL: str = "https://api.render.com/v1"
    RENDER_API_KEY: str = ""
    RENDER_SERVICE_ID: str = ""

    # ------------------------------------------------------------------
    # AI behaviour
    # ------------------------------------------------------------------
    AI_TIMEOUT_SECONDS: float = 90.0
    # Short per-request timeout for fail-fast + fallback (distinct from overall AI_TIMEOUT).
    AI_REQUEST_TIMEOUT_SECONDS: float = 35.0
    AI_MAX_TOKENS: int = 4096
    AI_MAX_RETRIES: int = 3
    AI_TEMPERATURE: float = 0.1
    # Fallback: if primary model times out / fails, retry once with FAST_MODEL.
    AI_MODEL_FALLBACK: bool = True

    # Caching (exact cache keyed by hash(model + system_prompt + user_prompt)).
    AI_CACHE_ENABLED: bool = True
    AI_CACHE_TTL_SECONDS: int = 3600
    AI_CACHE_MAX_SIZE: int = 128
    # Optional semantic cache (needs EMBEDDING_MODEL; degrades gracefully if it fails).
    AI_CACHE_SEMANTIC_ENABLED: bool = False
    AI_CACHE_SEMANTIC_THRESHOLD: float = 0.9

    # ------------------------------------------------------------------
    # Sandbox
    # ------------------------------------------------------------------
    SANDBOX_MODE: str = "local"  # "docker" | "local"
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
    # Repository / environment
    # ------------------------------------------------------------------
    REPO_ROOT: str = str(Path(__file__).resolve().parent.parent.parent)
    # The "patient" demo API (used by the detector). When empty we call the
    # in-process FastAPI app directly, which makes the demo self-contained.
    DEMO_API_BASE_URL: str = ""

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    HTTP_TIMEOUT_SECONDS: float = 15.0

    @property
    def has_nvidia(self) -> bool:
        return bool(self.NVIDIA_API_KEY)

    @property
    def has_github(self) -> bool:
        return bool(self.GITHUB_TOKEN)

    @property
    def has_render(self) -> bool:
        return bool(self.RENDER_API_KEY)

    def secret_scan_patterns(self) -> list[str]:
        """High-value secret names for sanitisation (case-insensitive)."""
        return [
            "nvidia_api_key",
            "github_token",
            "render_api_key",
            "openai_api_key",
            "anthropic_api_key",
            "stripe",
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
