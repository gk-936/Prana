from __future__ import annotations

import httpx

from framework.ai.base import ChatResponse, Message, Role, ToolCall, ToolSchema, Usage
from framework.errors import ProviderError

_ROLE_MAP = {Role.USER: "user", Role.ASSISTANT: "model", Role.SYSTEM: "user", Role.TOOL: "user"}


class GeminiProvider:
    name = "gemini"
    supports_native_tools = True

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash",
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not configured")
        contents = [
            {"role": _ROLE_MAP[m.role], "parts": [{"text": m.content}]} for m in messages
        ]
        payload: dict = {"contents": contents, "generationConfig": {"temperature": temperature}}
        if tools:
            payload["tools"] = [{"function_declarations": [t["function"] for t in tools]}]
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc
        return self._decode(resp.json())

    @staticmethod
    def _decode(data: dict) -> ChatResponse:
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text_parts, tool_calls = [], []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(ToolCall(id=str(i), name=fc["name"], arguments=fc.get("args", {})))
        return ChatResponse(
            content="".join(text_parts) or None, tool_calls=tool_calls, usage=Usage(), raw=data
        )
