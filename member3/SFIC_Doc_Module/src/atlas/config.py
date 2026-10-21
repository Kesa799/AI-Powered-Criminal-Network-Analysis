from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas.errors import ConfigError

# Tesseract is installed in different places depending on how it was set up.
# The historical default only covers a system-wide install under Program Files,
# so the other common locations are probed as well.
_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _resolve_tesseract_cmd(configured: str) -> str:
    """Return a usable Tesseract executable path.

    An explicitly configured path is always honoured - if it is wrong the OCR
    engine reports that clearly instead of silently using a different binary.
    Only the *default* is resolved, so a machine with Tesseract somewhere other
    than Program Files still works.
    """
    cmd = (configured or "").strip()
    if cmd and cmd != _TESSERACT_CANDIDATES[0]:
        return cmd
    for candidate in _TESSERACT_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    return cmd


class AtlasSettings(BaseSettings):
    """Configuration settings for ATLAS pipeline loaded from environment and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Settings
    LLM_PROVIDER: str = "mock"
    LLM_MODEL: str = ""
    # Comma-separated allow-list of providers offered by the dev UI. When empty the
    # UI offers every provider whose credentials are configured.
    LLM_PROVIDERS_ENABLED: str = ""
    OPENAI_API_KEY: SecretStr | None = None
    GEMINI_API_KEY: SecretStr | None = None
    GROQ_API_KEY: SecretStr | None = None
    OPENAI_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT_S: float = 60.0
    LLM_MAX_ATTEMPTS: int = 3
    # Upper bound on the tokens a single extraction call may generate. Providers apply
    # their own default when this is unset, which can truncate a schema-valid
    # document mid-object (the provider then reports the truncation as a schema
    # validation failure). 0 leaves the provider default in place.
    LLM_MAX_COMPLETION_TOKENS: int = 8192
    LLM_CHUNK_CHARS: int = 12000
    MAX_LLM_CALLS_PER_RUN: int = 40
    # Client-side pacing (prevents burst 429s). 0 max requests disables the window.
    LLM_MAX_REQUESTS_PER_MINUTE: int = 30
    LLM_RATE_WINDOW_S: float = 60.0
    # Minimum spacing between calls; 0 derives it from the request budget.
    LLM_MIN_INTERVAL_S: float = 0.0

    # OCR Settings
    OCR_ENGINE: str = "tesseract"
    OCR_LANGS: str = "eng"
    OCR_DPI: int = 300
    OCR_PSM: int = 3
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSDATA_PREFIX: str = ""
    ATLAS_REQUIRE_TESSERACT: bool = True
    OCR_ID_AUTOTRUST_MIN_CONF: float | None = None

    # Ingestion / Extraction Limits
    PDF_TEXT_MIN_CHARS: int = 25
    MAX_FILE_MB: int = 50
    MAX_PDF_PAGES: int = 60
    MAX_IMAGE_PIXELS: int = 60_000_000
    XLSX_FULL_LOAD_MB: int = 15
    DEFAULT_PHONE_REGION: str = "IN"

    # Paths & Safety
    DATA_DIR: str = "./data"
    OUTPUT_DIR: str = "./outputs"
    ATLAS_SYNTHETIC_ONLY: bool = True

    # Dev 2 Integration
    DEV2_BASE_URL: str = ""
    DEV2_TOKEN: SecretStr | None = None

    @field_validator("OCR_ID_AUTOTRUST_MIN_CONF", mode="before")
    @classmethod
    def _parse_optional_float(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v

    @field_validator("TESSERACT_CMD", mode="before")
    @classmethod
    def _resolve_tesseract(cls, v: Any) -> Any:
        """Point at a Tesseract install that actually exists on this machine."""
        if v is None:
            return _resolve_tesseract_cmd("")
        return _resolve_tesseract_cmd(str(v))

    @field_validator("OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "DEV2_TOKEN", mode="before")
    @classmethod
    def _parse_optional_secret(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def validate_provider_credentials(self) -> AtlasSettings:
        """Ensure required credentials are configured for active LLM provider without leaking secrets."""
        provider = self.LLM_PROVIDER.lower().strip()
        if provider == "openai" and (not self.OPENAI_API_KEY or not self.OPENAI_API_KEY.get_secret_value().strip()):
            raise ConfigError(
                "Missing required configuration: OPENAI_API_KEY must be configured when LLM_PROVIDER is 'openai'."
            )
        if provider == "gemini" and (not self.GEMINI_API_KEY or not self.GEMINI_API_KEY.get_secret_value().strip()):
            raise ConfigError(
                "Missing required configuration: GEMINI_API_KEY must be configured when LLM_PROVIDER is 'gemini'."
            )
        if provider == "groq":
            has_groq = self.GROQ_API_KEY and self.GROQ_API_KEY.get_secret_value().strip()
            has_openai = self.OPENAI_API_KEY and self.OPENAI_API_KEY.get_secret_value().strip()
            if not has_groq and not has_openai:
                raise ConfigError(
                    "Missing required configuration: GROQ_API_KEY must be configured when LLM_PROVIDER is 'groq'."
                )
        return self


_settings_instance: AtlasSettings | None = None


def get_settings(*, reload: bool = False) -> AtlasSettings:
    """Return cached singleton instance of AtlasSettings."""
    global _settings_instance
    if _settings_instance is None or reload:
        _settings_instance = AtlasSettings()
    return _settings_instance


__all__ = ["AtlasSettings", "get_settings"]
