"""Semantic retrieval over ingested documents."""

from __future__ import annotations

import json
from pathlib import Path

from ..memory.embeddings import EmbeddingIndex


class RagRetriever:
    """Search ingested documents using embedding similarity."""

    def __init__(self, index_dir: Path, embedding_index: EmbeddingIndex):
        self.index_dir = Path(index_dir)
        self.embedding_index = embedding_index

    def search(self, query: str, top_k: int = 5) -> str:
        """Search across all indexed documents.  Returns formatted result."""
        if not query.strip():
            return "请提供搜索关键词。"

        self.embedding_index.load_index()
        hits = self.embedding_index.search(query, top_k=top_k)
        if not hits:
            return f"未在已索引的文档中找到与 '{query}' 相关的内容。"

        _SNIPPET_MAX = 300
        doc_chunks: dict[str, list[str]] = {}
        for hit in hits:
            eid: str = hit["id"]
            doc_id, _, _ = eid.partition("::C")
            if doc_id not in doc_chunks:
                chunks_path = self.index_dir / doc_id / "chunks.json"
                try:
                    doc_chunks[doc_id] = json.loads(chunks_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    doc_chunks[doc_id] = []

        lines: list[str] = []
        for hit in hits:
            eid = hit["id"]
            doc_id, _, chunk_key = eid.partition("::C")
            try:
                chunk_idx = int(chunk_key)
            except ValueError:
                chunk_idx = 0
            score = hit.get("score", 0.0)

            chunks = doc_chunks.get(doc_id, [])
            snippet = ""
            if 0 <= chunk_idx < len(chunks):
                snippet = chunks[chunk_idx][:_SNIPPET_MAX].replace("\n", " ")

            lines.append(f"[{doc_id}] (相似度 {score:.2f})")
            if snippet:
                lines.append(f"   {snippet}...")
            lines.append("")

        return "\n".join(lines).strip()
