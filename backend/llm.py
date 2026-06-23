"""LLM adapter for PRANA WhatsApp conversations.

OpenRouter is the primary hosted provider. Ollama is the local fallback.
The scoring engine should remain deterministic; this adapter is for language
understanding, response drafting, and structured extraction only.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
)
from backend.logger import get_logger

_log = get_logger("llm")


@dataclass
class LLMMessage:
    role: str
    content: str


class LLMClient:
    def __init__(
        self,
        provider: str = LLM_PROVIDER,
        openrouter_api_key: str = OPENROUTER_API_KEY,
        openrouter_base_url: str = OPENROUTER_BASE_URL,
        openrouter_model: str = OPENROUTER_MODEL,
        ollama_base_url: str = OLLAMA_BASE_URL,
        ollama_model: str = OLLAMA_MODEL,
    ):
        self.provider = provider
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_base_url = openrouter_base_url.rstrip("/")
        self.openrouter_model = openrouter_model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model

    def chat(self, messages: List[LLMMessage], temperature: float = 0.2) -> str:
        """Return a model response, preferring OpenRouter with Ollama fallback."""
        if self.provider == "ollama":
            return self._chat_ollama(messages, temperature)

        try:
            return self._chat_openrouter(messages, temperature)
        except Exception as error:
            if self.ollama_model:
                _log.warning("OpenRouter failed, falling back to Ollama: %s", error)
                return self._chat_ollama(messages, temperature)
            raise

    def extract_sleep_checkin(self, user_message: str) -> Dict[str, Any]:
        """Extract deterministic sleep check-in fields from simple numbered replies."""
        normalized = user_message.strip().lower()

        if normalized in {"1", "comfortable", "slept comfortably", "cool enough"}:
            return {
                "sleep_environment": "comfortable",
                "sleep_quality": "good",
                "cooling_issue": False,
                "power_issue": False,
                "confidence": "high",
            }
        if normalized in {"2", "warm", "warm but manageable", "manageable"}:
            return {
                "sleep_environment": "warm_manageable",
                "sleep_quality": "moderate",
                "cooling_issue": False,
                "power_issue": False,
                "confidence": "high",
            }
        if normalized in {"3", "too hot", "too hot to sleep", "too hot to sleep well"}:
            return {
                "sleep_environment": "too_hot",
                "sleep_quality": "poor",
                "cooling_issue": True,
                "power_issue": False,
                "confidence": "high",
            }
        if normalized in {"4", "power cut", "no fan", "fan issue", "ac issue", "fan/ac or power issue"}:
            return {
                "sleep_environment": "cooling_unavailable",
                "sleep_quality": "poor",
                "cooling_issue": True,
                "power_issue": True,
                "confidence": "high",
            }

        prompt = [
            LLMMessage(
                role="system",
                content=(
                    "Extract PRANA sleep recovery check-in data. Return only compact JSON "
                    "with sleep_environment, sleep_quality, cooling_issue, power_issue, confidence."
                ),
            ),
            LLMMessage(role="user", content=user_message),
        ]
        response = self.chat(prompt, temperature=0)
        return {"raw_llm_response": response, "confidence": "low"}

    def _chat_openrouter(self, messages: List[LLMMessage], temperature: float) -> str:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        if not self.openrouter_model:
            raise RuntimeError("OPENROUTER_MODEL is not configured")

        payload = {
            "model": self.openrouter_model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://prana.local",
            "X-Title": "PRANA",
        }
        response = requests.post(
            f"{self.openrouter_base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _chat_ollama(self, messages: List[LLMMessage], temperature: float) -> str:
        if not self.ollama_model:
            raise RuntimeError("OLLAMA_MODEL is not configured")

        payload = {
            "model": self.ollama_model,
            "messages": [message.__dict__ for message in messages],
            "options": {"temperature": temperature},
            "stream": False,
        }
        response = requests.post(
            f"{self.ollama_base_url}/api/chat",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


def get_llm_client() -> LLMClient:
    return LLMClient()
