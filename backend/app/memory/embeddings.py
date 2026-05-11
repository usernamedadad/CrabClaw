"""Lightweight embedding index for semantic memory search.

Uses OpenAI-compatible embeddings API. No external vector database —
stores vectors as JSON files and computes cosine similarity in-memory
with numpy. Suitable for personal-scale usage (hundreds to thousands
of entries).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import List, Optional

import httpx


class EmbeddingIndex:
    """Semantic search over memory entries using cosine similarity."""

    def __init__(
        self,
        storage_dir: Path,
        api_key: str = "",
        base_url: str = "",
        model: str = "text-embedding-3-small",
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self._cache: dict[str, list[float]] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def index_entries(self, entries: list[dict], force: bool = False) -> int:
        """Index a batch of entries.  Each entry dict must have ``id`` and
        ``text`` keys.  Already-indexed entries are skipped unless *force*
        is True.

        Returns the number of new embeddings computed.
        """
        indexed = 0
        for entry in entries:
            eid = str(entry.get("id", ""))
            text = str(entry.get("text", ""))
            if not eid or not text.strip():
                continue
            if not force and self._load_cached(eid) is not None:
                continue
            emb = self._embed(text)
            if emb:
                self._save_cached(eid, emb)
                self._cache[eid] = emb
                indexed += 1
        return indexed

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return top-k matching entries with cosine similarity scores.

        Each result: ``{"id": ..., "text": ..., "score": 0.0-1.0}``.
        """
        if not query.strip():
            return []

        query_emb = self._embed(query)
        if not query_emb:
            return []

        scored: list[dict] = []
        for eid, emb in self._cache.items():
            score = self._cosine_similarity(query_emb, emb)
            if score > 0.0:
                scored.append({"id": eid, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def load_index(self) -> None:
        """Load all cached embeddings into memory (idempotent — skips if already loaded)."""
        if self._loaded:
            return
        self._cache.clear()
        for path in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                eid = path.stem
                emb = data.get("embedding") if isinstance(data, dict) else data
                if isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                    self._cache[eid] = [float(v) for v in emb]
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                continue
        self._loaded = True

    def _invalidate_cache(self) -> None:
        self._loaded = False

    # ------------------------------------------------------------------
    # embedding API call
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> Optional[list[float]]:
        endpoint = self._embeddings_url()
        try:
            resp = httpx.post(
                endpoint,
                json={"input": text, "model": self.model},
                headers=self._auth_header(),
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            vec = data["data"][0]["embedding"]
            return [float(v) for v in vec]
        except Exception:
            return None

    def _embeddings_url(self) -> str:
        if self.base_url:
            return f"{self.base_url}/embeddings"
        return "https://api.openai.com/v1/embeddings"

    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    def _cache_path(self, entry_id: str) -> Path:
        safe = entry_id.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{safe}.json"

    def _load_cached(self, entry_id: str) -> Optional[list[float]]:
        if entry_id in self._cache:
            return self._cache[entry_id]
        path = self._cache_path(entry_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            emb = data.get("embedding") if isinstance(data, dict) else data
            if isinstance(emb, list) and emb:
                vec = [float(v) for v in emb]
                self._cache[entry_id] = vec
                return vec
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass
        return None

    def _save_cached(self, entry_id: str, embedding: list[float]) -> None:
        path = self._cache_path(entry_id)
        path.write_text(
            json.dumps({"id": entry_id, "embedding": embedding}, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # math
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
