"""Document ingestion: file reading, chunking, embedding, indexing."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..memory.embeddings import EmbeddingIndex


class RagIngester:
    """Ingest documents into the RAG index.

    Zero external dependencies — uses the same EmbeddingIndex as
    semantic memory.  Supports .txt, .md, .py, .csv, .json files.
    """

    def __init__(self, index_dir: Path, embedding_index: EmbeddingIndex):
        self.index_dir = Path(index_dir)
        self.embedding_index = embedding_index
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def ingest_file(self, file_path: str | Path) -> dict:
        """Ingest a single file.  Returns metadata dict."""
        source = Path(file_path).expanduser().resolve()
        doc_id = source.stem[:48] or "doc"
        text = self._read_file(source)
        if text is None:
            return {"error": f"不支持的文件类型: {source.suffix}"}
        if not text.strip():
            return {"error": "文件内容为空"}

        chunks = self._chunk_text(text)
        if not chunks:
            return {"error": "无法提取文本块"}

        doc_dir = self.index_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        entries = []
        for idx, chunk in enumerate(chunks):
            eid = f"{doc_id}::C{idx}"
            entries.append({"id": eid, "text": chunk})

        indexed = self.embedding_index.index_entries(entries, force=True)

        (doc_dir / "chunks.json").write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        meta = {
            "doc_id": doc_id,
            "source": str(source),
            "chunks": len(chunks),
            "indexed": indexed,
            "ingested_at": datetime.now().isoformat(),
        }
        (doc_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return meta

    def list_docs(self) -> list[dict]:
        """List all ingested documents with metadata."""
        docs: list[dict] = []
        for doc_dir in sorted(self.index_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            meta_path = doc_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                docs.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return docs

    def delete_doc(self, doc_id: str) -> bool:
        """Remove a document and its index."""
        import shutil
        doc_dir = self.index_dir / doc_id
        if not doc_dir.exists():
            return False
        shutil.rmtree(doc_dir, ignore_errors=True)
        for emb_file in list(self.embedding_index.storage_dir.glob(f"{doc_id}::*.json")):
            emb_file.unlink(missing_ok=True)
        return True

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    _SUPPORTED_SUFFIXES = {".txt", ".md", ".py", ".csv", ".json", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".xml", ".html", ".js", ".ts", ".vue", ".css", ".sql", ".sh", ".bat", ".ps1"}

    def _read_file(self, path: Path) -> Optional[str]:
        suffix = path.suffix.lower()
        if suffix not in self._SUPPORTED_SUFFIXES:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return None

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
        """Split text into overlapping chunks at paragraph boundaries."""
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            stripped = para.strip()
            if not stripped:
                continue
            if len(current) + len(stripped) < chunk_size:
                current = f"{current}\n\n{stripped}".strip() if current else stripped
            else:
                if current:
                    chunks.append(current)
                current = stripped
                # Handle very long paragraphs
                while len(current) >= chunk_size:
                    split_at = current.rfind("。", 0, chunk_size)
                    if split_at < chunk_size // 2:
                        split_at = current.rfind("\n", 0, chunk_size)
                    if split_at < chunk_size // 2:
                        split_at = chunk_size
                    chunks.append(current[:split_at + 1])
                    current = current[max(0, split_at - overlap):].lstrip()
        if current:
            chunks.append(current)
        return chunks
