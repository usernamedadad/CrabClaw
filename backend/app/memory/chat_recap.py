"""Session summarizer for archived conversation notes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from langchain_openai import ChatOpenAI


class SessionSummarizer:
    def __init__(
        self,
        workspace_manager,
        model_id: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.workspace = workspace_manager
        self.model_id = model_id
        self.api_key = api_key
        self.base_url = base_url

    async def summarize_session(self, messages: List[dict], last_n: int = 10, session_id: str | None = None) -> Optional[str]:
        if not messages:
            return None
        excerpt = self._extract_excerpt(messages, last_n)
        if not excerpt:
            return None

        slug = await self._generate_slug(excerpt)
        summary = await self._generate_summary(excerpt)
        if not slug or not summary:
            return None

        filename = f"{datetime.now().strftime('%Y-%m-%d')}-{slug}.md"
        self.workspace.save_session_summary(filename, summary)
        return filename

    @staticmethod
    def _extract_excerpt(messages: List[dict], last_n: int = 10) -> str:
        items: List[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in {"user", "assistant"} or not content:
                continue
            text = str(content)
            if len(text) > 500:
                text = text[:500] + "..."
            items.append(f"[{role.upper()}] {text}")
        if len(items) > last_n * 2:
            items = items[-(last_n * 2) :]
        return "\n".join(items)

    async def _generate_slug(self, excerpt: str) -> str:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", excerpt.lower())
        common = {
            "the", "and", "for", "with", "that", "this", "you", "your", "about", "what", "when", "where"
        }
        filtered = [w for w in words if w not in common]
        if not filtered:
            return "conversation"
        top = filtered[:3]
        return "-".join(top)

    async def _generate_summary(self, excerpt: str) -> str:
        if not (self.model_id and self.api_key):
            return self._simple_summary(excerpt)

        try:
            model = ChatOpenAI(
                model=self.model_id,
                api_key=self.api_key,
                base_url=self.base_url or None,
                temperature=0.2,
            )
            prompt = (
                "请用 Markdown 总结以下对话，包含三个部分：主题、关键信息、待办。"
                "请保持简洁，控制在 220 字以内。\n\n对话内容：\n"
                f"{excerpt}"
            )
            response = await model.ainvoke(prompt)
            text = getattr(response, "content", "")
            if isinstance(text, list):
                text = "\n".join(str(item) for item in text)
            if not text:
                return self._simple_summary(excerpt)
            return self._header() + str(text)
        except Exception:
            return self._simple_summary(excerpt)

    @staticmethod
    def _header() -> str:
        return (
            "---\n"
            f"date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            "type: session-summary\n"
            "---\n\n"
        )

    def _simple_summary(self, excerpt: str) -> str:
        body = excerpt[:500] + ("..." if len(excerpt) > 500 else "")
        return self._header() + "# 会话摘要\n\n" + body
