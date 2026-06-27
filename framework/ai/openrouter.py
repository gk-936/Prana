from __future__ import annotations

import json

import httpx

from framework.ai.base import ChatResponse, Message, ToolCall, ToolSchema, Usage
from framework.errors import ProviderError


class OpenRouterProvider:
    name = "openrouter"
    supports_native_tools = True

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://openrouter.ai/api/v1", timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, tools: list[ToolSchema] | None = None,
             temperature: float = 0.2) -> ChatResponse:
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        payload: dict = {
            "model": self.model,
            "messages": [self._encode(m) for m in messages],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://prana.local",
            "X-Title": "PRANA",
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions",
                              headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc
        return self._decode(resp.json())

    @staticmethod
    def _encode(m: Message) -> dict:
        out: dict = {"role": m.role.value, "content": m.content}
        if m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in m.tool_calls
            ]
        return out

    @staticmethod
    def _decode(data: dict) -> ChatResponse:
        msg = data["choices"][0]["message"]
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            args = fn.get("arguments") or "{}"
            tool_calls.append(ToolCall(
                id=tc.get("id", ""), name=fn["name"],
                arguments=json.loads(args) if isinstance(args, str) else args,
            ))
        u = data.get("usage") or {}
        return ChatResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
            raw=data,
        )
