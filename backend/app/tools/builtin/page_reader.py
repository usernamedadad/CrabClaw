"""Web fetch tool to extract readable page text."""

from __future__ import annotations

import re
import urllib.request


class WebFetchTool:
    def __init__(self, timeout: int = 15, max_content_size: int = 50000):
        self.timeout = timeout
        self.max_content_size = max_content_size
        self.user_agent = "Mozilla/5.0 (compatible; CrabClawBot/1.0)"

    def run(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "URL must start with http:// or https://"

        req = urllib.request.Request(url)
        req.add_header("User-Agent", self.user_agent)
        req.add_header("Accept", "text/html,application/xhtml+xml")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text/html" not in ctype:
                    return f"Unsupported content type: {ctype}"
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            return f"Fetch failed: {exc}"

        md = self._html_to_text(html)
        if len(md) > self.max_content_size:
            md = md[: self.max_content_size] + f"\n\n... (truncated, total {len(md)} chars)"
        return md

    def _html_to_text(self, html: str) -> str:
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        title = ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            title = self._clean(title_match.group(1))

        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, flags=re.IGNORECASE | re.DOTALL)
        if body_match:
            html = body_match.group(1)

        html = re.sub(r"<(h[1-6])[^>]*>(.*?)</\1>", lambda m: f"\n{self._clean(m.group(2))}\n", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"<[^>]+>", "", html)

        text = self._clean(html)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if title:
            return f"# {title}\n\n{text}".strip()
        return text.strip()

    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        return text.strip()
