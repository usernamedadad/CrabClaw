"""Web search tool backed by SerpAPI."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


class WebSearchTool:
    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        timeout: int = 10,
        engine: str = "google",
    ):
        self.api_key = api_key or os.getenv("SERPAPI_API", "")
        self.max_results = max_results
        self.timeout = timeout
        self.engine = engine
        self.base_url = "https://serpapi.com/search.json"

    def run(self, query: str, count: int | None = None) -> str:
        if not query.strip():
            return "Search query cannot be empty"
        if not self.api_key:
            return "SERPAPI_API is not configured"

        params = {
            "engine": self.engine,
            "q": query,
            "num": str(count or self.max_results),
            "api_key": self.api_key,
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return f"Web search failed: {exc}"

        items = payload.get("organic_results", [])
        if not items:
            answer_box = payload.get("answer_box", {})
            snippet = answer_box.get("snippet") or answer_box.get("answer") or ""
            if snippet:
                return f"Answer box:\n{snippet}"
            return f"No result for: {query}"

        lines = [f"Found {len(items)} results:"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.get('title', '(no title)')}")
            lines.append(f"   URL: {item.get('link', '')}")
            snippet = item.get("snippet", "")
            if snippet:
                lines.append("   " + snippet[:220])
        return "\n".join(lines)
