"""Eval configuration. Reads .env so it inherits the agent's provider config."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── paths ─────────────────────────────────────────────────────────────
    eval_file: str = "data/synthetic_sft/eval_sft.jsonl"
    results_dir: str = "data/eval_results"

    # ── run phase ─────────────────────────────────────────────────────────
    temperature: float = 0.2
    max_tokens: int = 1024
    workers: int = 8

    # ── score phase ───────────────────────────────────────────────────────
    # Generic similarity threshold for tool-arg value comparison.
    # Kept the name `tfidf_threshold` for parity with santa-post-training.
    tfidf_threshold: float = 0.7

    # ── critic (LLM judge) — default resolves to the .env Anthropic provider ─
    critic_model: str = Field("", alias="EVAL_CRITIC_MODEL")
    critic_base_url: str = Field("", alias="EVAL_CRITIC_BASE_URL")
    critic_api_key: str = Field("", alias="EVAL_CRITIC_API_KEY")
