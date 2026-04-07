"""Memory tool helpers."""

from __future__ import annotations

import re
from datetime import datetime


class MemoryTool:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager

    def search(self, keyword: str, context_lines: int = 3) -> str:
        if not keyword.strip():
            return "Please provide a keyword."
        results = self.workspace.search_memory_enhanced(keyword, context_lines=context_lines)
        if not results:
            return f"No memory found for '{keyword}'."

        blocks: list[str] = []
        count = 0
        for item in results:
            source = item["source"]
            for match in item["matches"]:
                count += 1
                start = match["start_line"]
                end = match["end_line"]
                span = f"line {start}" if start == end else f"line {start}-{end}"
                blocks.append(f"{source} ({span}):\n{match['content']}")
        return f"Found {count} matches:\n\n" + "\n\n".join(blocks)

    def get(self, filename: str | None = None, lines: str | None = None) -> str:
        start_line = None
        end_line = None
        if lines:
            match = re.match(r"(\d+)(?:\s*-\s*(\d+))?", lines)
            if match:
                start_line = int(match.group(1))
                if match.group(2):
                    end_line = int(match.group(2))
        if not filename:
            filename = f"{datetime.now().strftime('%Y-%m-%d')}.md"
        if not filename.endswith(".md"):
            filename += ".md"

        content = self.workspace.read_memory_lines(filename, start_line, end_line)
        if content is None:
            files = "\n".join(f"- {f['name']}" for f in self.workspace.list_memory_files())
            return f"File not found: {filename}\nAvailable files:\n{files or '- (none)'}"
        if not content:
            return f"File is empty: {filename}"
        return f"{filename}\n{content}"

    def add(self, content: str, category: str | None = None) -> str:
        text = (content or "").strip()
        if not text:
            return "Memory content is empty."

        normalized_category = (category or "").strip().lower()
        valid_categories = {"preference", "decision", "entity", "fact"}
        if normalized_category:
            if normalized_category in valid_categories:
                self.workspace.append_classified_memory(text, normalized_category)
                return f"Added to daily memory [{normalized_category}]"

            self.workspace.append_to_daily_memory(text)
            return f"Added to daily memory (unknown category '{normalized_category}' ignored)"

        self.workspace.append_to_daily_memory(text)
        return "Added memory to today's journal"

    def update_longterm(self, content: str, category: str | None = None) -> str:
        normalized_category = (category or "").strip().lower() or "fact"
        self.workspace.append_to_longterm_memory(content, normalized_category)
        return "Long-term memory updated"

    def list(self) -> str:
        files = self.workspace.list_memory_files()
        if not files:
            return "No memory files"
        lines = ["Memory files:"]
        for item in files:
            size_kb = item["size"] / 1024
            lines.append(f"- {item['name']} ({item['type']}, {size_kb:.1f} KB)")
        return "\n".join(lines)

    def cleanup(self, days: int = 30) -> str:
        deleted = self.workspace.cleanup_old_memories(days)
        if not deleted:
            return f"No files removed (keep last {days} days)."
        return "Removed files:\n" + "\n".join(f"- {name}" for name in deleted)

    def get_active_context(self) -> str:
        content = self.workspace.load_active_context()
        if not content:
            return "No active context is empty."
        return f"Active context:\n" + content

    def set_active_context(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return "Active context content is empty."
        self.workspace.save_active_context(text)
        return "Active context updated."

    def clear_active_context(self) -> str:
        self.workspace.save_active_context("")
        return "Active context cleared."
