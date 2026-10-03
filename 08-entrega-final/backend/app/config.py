"""Configuración por variables de entorno con prefijo ``PANEL_`` (ver .env.example)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PANEL_", extra="ignore")

    redis_url: RedisDsn = "redis://localhost:6379/0"
    config_dir: Path = Path("../config")
    demo_dir: Path = Path("../demo/laboratorio3")

    # Modelo: demo (determinista, sin red) o live (proveedor compatible con OpenAI).
    llm_mode: Literal["demo", "live"] = "demo"
    llm_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = Field(default=None, exclude=True, repr=False)
    chat_model: str = "gpt-6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    max_output_tokens: int = Field(default=4000, ge=1, le=10000)
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=64, le=3072)
    rag_index: str = Field(default="panellab:chunks", pattern=r"^[A-Za-z0-9:_-]{1,64}$")

    # Presupuesto compartido para el modo live (se persiste en Redis).
    budget_cap_usd: float = Field(default=0.95, gt=0)
    budget_prior_usd: float = Field(default=0.0, ge=0)

    # Observabilidad.
    phoenix_endpoint: str = "http://phoenix:6006"
    phoenix_project: str = "panellab"
    trace_content: bool = True


def get_settings() -> Settings:
    return Settings()
