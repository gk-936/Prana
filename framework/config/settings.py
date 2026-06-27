from __future__ import annotations

from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class FrameworkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_providers: Annotated[List[str], NoDecode] = ["openrouter", "ollama"]
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    agent_max_steps: int = 5
    agent_temperature: float = 0.2
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_bot_number: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    @field_validator("llm_providers", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v
