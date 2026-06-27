from __future__ import annotations

import json
import re
import uuid

from framework.ai.base import Message, Role, ToolCall

_INSTRUCTION = (
    "You can call tools. Reply with ONLY a single JSON object and nothing else.\n"
    'To call a tool: {{"tool": "<tool_name>", "args": {{<json args>}}}}\n'
    'To answer the user: {{"answer": "<your reply>"}}\n'
    "Available tools:\n{tools}"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_react_messages(messages: list[Message], schemas: list[dict]) -> list[Message]:
    tool_lines = []
    for s in schemas:
        fn = s["function"]
        tool_lines.append(
            f"- {fn['name']}: {fn['description']} params={json.dumps(fn['parameters'])}"
        )
    instruction = _INSTRUCTION.format(tools="\n".join(tool_lines) or "(none)")
    return list(messages) + [Message(role=Role.SYSTEM, content=instruction)]


def _extract_json(content: str) -> dict | None:
    for pattern in (_FENCE_RE, _OBJ_RE):
        m = pattern.search(content)
        if m:
            try:
                return json.loads(m.group(1) if pattern is _FENCE_RE else m.group(0))
            except json.JSONDecodeError:
                continue
    return None


def parse_react_response(content: str) -> tuple[list[ToolCall], str | None]:
    obj = _extract_json(content)
    if isinstance(obj, dict) and "tool" in obj:
        return (
            [ToolCall(id=str(uuid.uuid4()), name=obj["tool"], arguments=obj.get("args", {}))],
            None,
        )
    if isinstance(obj, dict) and "answer" in obj:
        return [], str(obj["answer"])
    return [], content
