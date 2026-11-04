"""Synthetic-data-generator settings (separate from Noble Agent's settings).

Reads `src/synthetic/.env` (or anything else `python-dotenv` has loaded into
`os.environ`). All fields prefixed `CA_` so they don't collide with Noble's
own provider keys — you can run CA on GPT-4o-mini while Noble runs Claude.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve().parent


class SyntheticSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_HERE / ".env"),
        env_file_encoding="utf-8",
        env_prefix="CA_",
        extra="ignore",
        case_sensitive=False,
    )

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = 0.9
    max_tokens: int = 300

    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"


@lru_cache(maxsize=1)
def get_synthetic_settings() -> SyntheticSettings:
    return SyntheticSettings()
