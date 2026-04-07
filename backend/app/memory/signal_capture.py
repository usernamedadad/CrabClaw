"""Rule-based memory capture manager."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import List, Optional


MEMORY_TRIGGERS = [
    (r"remember|keep in mind|记住|记下", "fact"),
    (r"prefer|like|love|hate|我喜欢|我偏好|我不喜欢|讨厌", "preference"),
    (r"decide|decision|决定|选定|确定用", "decision"),
    (r"my name is|我的名字|我叫", "entity"),
    (r"@|email|邮箱", "entity"),
    (r"phone|电话|\+\d{7,}", "entity"),
]

IDENTITY_PATTERNS = [
    re.compile(r"(?:my\s+name\s+is|i\s+am)\s+([A-Za-z][A-Za-z\s\-]{1,40})", re.IGNORECASE),
    re.compile(r"(?:我的名字是|我叫)\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{1,20})", re.IGNORECASE),
]


class MemoryCaptureManager:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager
        self._compiled = [(re.compile(pattern, re.IGNORECASE), category) for pattern, category in MEMORY_TRIGGERS]

    def capture(self, text: str) -> List[dict]:
        memories: List[dict] = []
        seen: set[str] = set()

        for sentence in self._split_sentences(text):
            if len(sentence) < 5:
                continue

            category = self._match_trigger(sentence)
            if not category:
                continue

            content = self._extract_memory(sentence, category)
            if not content:
                continue

            key = content.lower().strip()
            if key in seen:
                continue

            if self.workspace.check_duplicate_memory(content, threshold=0.7):
                continue

            seen.add(key)
            memories.append(
                {
                    "content": content,
                    "category": category,
                    "timestamp": datetime.now().strftime("%H:%M"),
                }
            )

        return memories

    async def acapture(self, text: str) -> List[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.capture, text)

    def capture_and_store(self, text: str, date: datetime | None = None) -> List[dict]:
        memories = self.capture(text)
        stored: List[dict] = []

        for memory in memories:
            if memory.get("category") == "entity":
                identity = self._extract_identity(memory.get("content", ""))
                if identity:
                    self.workspace.append_to_longterm_memory(f"用户身份：{identity}", "entity")

            self.workspace.append_classified_memory(
                content=memory["content"],
                category=memory["category"],
                date=date,
            )
            stored.append(memory)

        return stored

    async def acapture_and_store(self, text: str, date: datetime | None = None) -> List[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.capture_and_store, text, date)

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        return [s.strip() for s in re.split(r"[。！？.!?]\s*|\n+", text) if s.strip()]

    def _match_trigger(self, sentence: str) -> Optional[str]:
        for pattern, category in self._compiled:
            if pattern.search(sentence):
                return category
        return None

    @staticmethod
    def _extract_memory(sentence: str, category: str) -> Optional[str]:
        content = re.sub(r"^(user|assistant|用户|我|你)[:：]\s*", "", sentence.strip(), flags=re.IGNORECASE)
        content = content.strip('"\'')

        if len(content) < 5:
            return None

        if category == "preference" and not content.lower().startswith(("user", "用户")):
            return f"User preference: {content}"

        return content

    @staticmethod
    def _extract_identity(text: str) -> Optional[str]:
        raw = (text or "").strip()
        if not raw:
            return None

        for pattern in IDENTITY_PATTERNS:
            matched = pattern.search(raw)
            if not matched:
                continue
            identity = matched.group(1).strip().strip("。,.，")
            if identity:
                return identity

        return None

    def analyze_conversation(self, messages: List[dict]) -> List[dict]:
        all_memories: List[dict] = []
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                all_memories.extend(self.capture(msg["content"]))
        return all_memories
