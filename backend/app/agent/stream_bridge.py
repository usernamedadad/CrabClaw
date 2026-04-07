"""Helpers for converting LangChain messages to API-friendly payloads."""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage


def extract_text_chunk(token: Any) -> str:
    text = getattr(token, "text", None)
    if isinstance(text, str) and text:
        return text

    content = getattr(token, "content", None)
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
        return "".join(chunks)

    return ""


def message_to_history(message: BaseMessage) -> Optional[dict]:
    if isinstance(message, HumanMessage):
        return {
            "role": "user",
            "content": _message_text(message),
        }

    if isinstance(message, AIMessage):
        payload: dict = {
            "role": "assistant",
            "content": _message_text(message),
        }
        if message.tool_calls:
            payload["metadata"] = {
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                        },
                    }
                    for tc in message.tool_calls
                ]
            }
        return payload

    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": _message_text(message),
            "metadata": {
                "tool_call_id": getattr(message, "tool_call_id", None),
            },
        }

    return None


def find_final_assistant_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            text = _message_text(msg)
            if text:
                return text
    return ""


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for block in content:
            if isinstance(block, str):
                pieces.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                pieces.append(str(block.get("text", "")))
        return "".join(pieces)
    return str(content)
