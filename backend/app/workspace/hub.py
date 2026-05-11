"""Workspace manager for CrabClaw."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.embeddings import EmbeddingIndex

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

CONFIG_FILES = [
    "AGENTS",
    "PROFILE",
    "MERMORY",
    "IDENTITY",
    "USER",
    "SOUL",
    "BOOTSTRAP",
    "HEARTBEAT",
]

CONFIG_ALIASES = {
    "KICKOFF": "AGENTS",
    "PRINCIPLES": "AGENTS",
    "MEMORY": "MERMORY",
    "KNOWLEDGE": "MERMORY",
}

LONGTERM_CONFIG_NAME = "MERMORY"
LONGTERM_FILE_NAME = "MERMORY.md"
LEGACY_LONGTERM_FILE_NAMES = {"MEMORY.md", "KNOWLEDGE.md"}

LONGTERM_SECTION_BY_CATEGORY = {
    "preference": "偏好",
    "decision": "决策",
    "fact": "重要事实",
    "entity": "用户身份",
}

LONGTERM_SECTION_ALIASES = {
    "偏好": ["偏好", "偏好（Preferences）", "Preferences"],
    "重要事实": ["重要事实", "重要事实（Important Facts）", "Important Facts"],
    "决策": ["决策", "决策（Decisions）", "Decisions"],
    "用户身份": ["用户身份", "身份", "Identity"],
}

IDENTITY_FIELDS = ["名称", "角色", "风格", "表情符号", "头像"]
USER_FIELDS = ["称呼", "长期目标", "输出语言", "回答长度", "沟通节奏", "时区"]
USER_REQUIRED_FIELDS = ["称呼", "长期目标", "输出语言", "回答长度", "沟通节奏"]
SOUL_FIELDS = ["核心准则", "边界", "风格"]

TEMPLATES_DIR = Path(__file__).parent / "presets"


def canonical_config_name(name: str) -> str:
    normalized = (name or "").strip().upper()
    if not normalized:
        return ""
    return CONFIG_ALIASES.get(normalized, normalized)


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_identity_name(identity_text: str | None) -> str | None:
    if not identity_text:
        return None
    for line in identity_text.splitlines():
        marker = None
        if "**Name:**" in line:
            marker = "**Name:**"
        elif "**名称：**" in line:
            marker = "**名称：**"
        elif "**名称:**" in line:
            marker = "**名称:**"

        if marker:
            name = line.split(marker, 1)[-1].strip()
            if name and not name.startswith("_"):
                return name
    return None


def _extract_field_value(text: str | None, label: str) -> str:
    if not text:
        return ""

    pattern = re.compile(
        rf"^\s*[-*]?\s*(?:\*\*)?{re.escape(label)}[：:](?:\*\*)?\s*(.*)$"
    )
    for line in text.splitlines():
        matched = pattern.match(line.strip())
        if not matched:
            continue
        value = (matched.group(1) or "").strip()
        if value and not value.startswith("_"):
            return value
    return ""


def get_default_global_config() -> dict:
    template_path = TEMPLATES_DIR / "defaults.json"
    if template_path.exists():
        return json.loads(template_path.read_text(encoding="utf-8"))
    return {
        "llm": {
            "model_id": "",
            "api_key": "",
            "base_url": "",
            "temperature": 0.4,
        },
        "tools": {
            "serpapi_api": "",
        },
    }


class WorkspaceManager:
    """Manage local workspace files under ~/.crabclaw."""

    def __init__(self, workspace_path: str | Path | None = None):
        base = Path(workspace_path).expanduser() if workspace_path else Path.home() / ".crabclaw" / "workspace"
        self.workspace_path = base
        self.root_path = self.workspace_path.parent
        self.memory_path = self.workspace_path / "memory"
        self.sessions_path = self.workspace_path / "sessions"
        self.skills_path = self.workspace_path / "skills"
        self._embeddings_path = self.memory_path / ".embeddings"
        self._embedding_index: Optional["EmbeddingIndex"] = None
        self._memory_content_hash = ""

    @property
    def global_config_path(self) -> Path:
        return self.root_path / "config.json"

    def _get_embedding_index(self) -> Optional["EmbeddingIndex"]:
        if self._embedding_index is not None:
            return self._embedding_index
        llm_cfg = self.get_llm_config()
        api_key = llm_cfg.get("api_key", "")
        base_url = llm_cfg.get("base_url", "")
        if not api_key:
            return None
        from ..memory.embeddings import EmbeddingIndex
        self._embeddings_path.mkdir(parents=True, exist_ok=True)
        self._embedding_index = EmbeddingIndex(
            storage_dir=self._embeddings_path,
            api_key=api_key,
            base_url=base_url,
        )
        self._embedding_index.load_index()
        return self._embedding_index

    def ensure_workspace_exists(self) -> None:
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.memory_path.mkdir(parents=True, exist_ok=True)
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        self.skills_path.mkdir(parents=True, exist_ok=True)

        for config_name in CONFIG_FILES:
            config_path = self.get_config_path(config_name)
            if not config_path.exists():
                self._create_default_config(config_name)

        if not self.global_config_path.exists():
            self.save_global_config(get_default_global_config())

        # 首次初始化时复制预置技能到 workspace/skills/
        self._install_preset_skills()

        # 把 .env 里的值同步到 config.json 里（如果 config.json 里的对应值为空）
        data = self.load_global_config()
        if not isinstance(data, dict):
            data = {}
        
        llm = data.get("llm", {})
        if not isinstance(llm, dict):
            llm = {}
        
        changed = False
        
        # 同步 model_id
        if not llm.get("model_id"):
            env_model = os.getenv("LLM_MODEL_ID")
            if env_model:
                llm["model_id"] = env_model
                changed = True
        
        # 同步 api_key
        if not llm.get("api_key"):
            env_key = os.getenv("LLM_API_KEY")
            if env_key:
                llm["api_key"] = env_key
                changed = True
        
        # 同步 base_url
        if not llm.get("base_url"):
            env_url = os.getenv("LLM_BASE_URL")
            if env_url:
                llm["base_url"] = env_url
                changed = True
        
        # 同步 temperature
        if llm.get("temperature") in {None, ""}:
            env_temp = os.getenv("LLM_TEMPERATURE")
            if env_temp:
                llm["temperature"] = float(env_temp)
                changed = True
        
        # 同步 search_api_key
        tools = data.get("tools", {})
        if not isinstance(tools, dict):
            tools = {}
        if not tools.get("serpapi_api"):
            env_search = os.getenv("SERPAPI_API")
            if env_search:
                tools["serpapi_api"] = env_search
                changed = True
        
        if changed:
            data["llm"] = llm
            data["tools"] = tools
            self.save_global_config(data)

    def get_config_path(self, name: str) -> Path:
        canonical_name = canonical_config_name(name)
        return self.workspace_path / f"{canonical_name}.md"

    def load_config(self, name: str) -> Optional[str]:
        path = self.get_config_path(name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def save_config(self, name: str, content: str) -> None:
        self.get_config_path(name).write_text(content, encoding="utf-8")

    def get_active_context_path(self) -> Path:
        return self.memory_path / "active_context.md"

    def load_active_context(self) -> str:
        path = self.get_active_context_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def save_active_context(self, content: str) -> None:
        self.get_active_context_path().write_text(content, encoding="utf-8")

    def list_configs(self) -> List[str]:
        return [name for name in CONFIG_FILES if self.get_config_path(name).exists()]

    def load_global_config(self) -> dict:
        if not self.global_config_path.exists():
            return {}
        try:
            return json.loads(self.global_config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save_global_config(self, config: dict) -> None:
        self.global_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_llm_config(self) -> dict:
        cfg = self.load_global_config().get("llm", {})

        temp_raw = cfg.get("temperature") if isinstance(cfg, dict) else None
        if temp_raw in {None, ""}:
            temp_raw = os.getenv("LLM_TEMPERATURE", 0.4)
        temperature = min(max(_safe_float(temp_raw, 0.4), 0.0), 2.0)

        return {
            "model_id": cfg.get("model_id") or os.getenv("LLM_MODEL_ID") or "gpt-4o-mini",
            "api_key": cfg.get("api_key") or os.getenv("LLM_API_KEY", ""),
            "base_url": cfg.get("base_url") or os.getenv("LLM_BASE_URL", ""),
            "temperature": temperature,
        }

    def get_search_api_key(self) -> str:
        cfg = self.load_global_config().get("tools", {})
        return cfg.get("serpapi_api") or os.getenv("SERPAPI_API", "")

    def _install_preset_skills(self) -> None:
        presets_dir = TEMPLATES_DIR.parent / "presets" / "skills"
        if not presets_dir.exists():
            return
        for skill_dir in presets_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            target = self.skills_path / skill_dir.name
            if target.exists():
                continue
            import shutil
            shutil.copytree(str(skill_dir), str(target))

    def _create_default_config(self, name: str) -> None:
        content = self._render_config_template(name)
        self.save_config(name, content)

    def _render_config_template(self, name: str) -> str:
        canonical_name = canonical_config_name(name)
        template_path = TEMPLATES_DIR / f"{canonical_name}.md"
        if template_path.exists():
            content = template_path.read_text(encoding="utf-8")
        else:
            content = f"# {canonical_name}\n\n(TODO)\n"
        return content.replace("{date}", datetime.now().strftime("%Y-%m-%d"))

    def reset_to_templates(
        self,
        reset_sessions: bool = False,
        reset_memory: bool = False,
        reset_global_config: bool = False,
    ) -> None:
        for name in CONFIG_FILES:
            self._create_default_config(name)

        if reset_sessions:
            for file in self.sessions_path.glob("*.json"):
                file.unlink(missing_ok=True)

        if reset_memory:
            for file in self.memory_path.glob("*.md"):
                file.unlink(missing_ok=True)

        if reset_global_config:
            self.save_global_config(get_default_global_config())

    def get_daily_memory_path(self, date: datetime | None = None) -> Path:
        date = date or datetime.now()
        return self.memory_path / f"{date.strftime('%Y-%m-%d')}.md"

    def append_to_daily_memory(self, content: str, date: datetime | None = None) -> None:
        path = self.get_daily_memory_path(date)
        stamp = datetime.now().strftime("%H:%M:%S")
        if not path.exists():
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {stamp}\n\n{content}\n")

    @staticmethod
    def _format_memory_tags(category: str, tags: Optional[List[str]] = None) -> str:
        normalized_category = (category or "fact").strip().lower()
        extra = [t.strip().lower() for t in (tags or []) if t and t.strip()]
        allowed = ["confirmed", "explicit", "sensitive"]
        ordered = [normalized_category] + [t for t in allowed if t in extra]
        return "".join(f"[{item}]" for item in ordered)

    def append_classified_memory(
        self,
        content: str,
        category: str,
        date: datetime | None = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        path = self.get_daily_memory_path(date)
        stamp = datetime.now().strftime("%H:%M")
        if not path.exists():
            path.write_text(f"# {path.stem}\n", encoding="utf-8")
        tag_text = self._format_memory_tags(category, tags)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {stamp} - auto-capture\n\n- {tag_text} {content}\n")

    def _append_bullet_to_longterm_section(self, markdown: str, section: str, bullet: str) -> str:
        lines = markdown.splitlines()
        heading = ""
        heading_idx = -1
        for candidate in LONGTERM_SECTION_ALIASES.get(section, [section]):
            candidate_heading = f"## {candidate}"
            if candidate_heading in lines:
                heading = candidate_heading
                heading_idx = lines.index(candidate_heading)
                break

        if heading_idx < 0:
            heading = f"## {section}"
            if markdown and not markdown.endswith("\n"):
                markdown += "\n"
            return markdown + f"\n{heading}\n\n{bullet}\n"

        next_heading_idx = len(lines)
        for idx in range(heading_idx + 1, len(lines)):
            if lines[idx].startswith("## "):
                next_heading_idx = idx
                break

        section_lines = lines[heading_idx + 1 : next_heading_idx]
        insert_at = heading_idx + 1
        for idx, line in enumerate(section_lines, start=heading_idx + 1):
            if line.strip().startswith("- "):
                insert_at = idx + 1

        if insert_at == heading_idx + 1:
            lines.insert(insert_at, "")
            insert_at += 1

        lines.insert(insert_at, bullet)

        if insert_at + 1 >= len(lines) or lines[insert_at + 1].strip() != "":
            lines.insert(insert_at + 1, "")

        return "\n".join(lines).rstrip() + "\n"

    def append_to_longterm_memory(self, content: str, category: str | None = None) -> None:
        text = (content or "").strip()
        if not text:
            return

        # 轻量去重：只拦截与长期记忆重复的条目，避免长期污染。
        longterm = self.load_config(LONGTERM_CONFIG_NAME) or ""
        if longterm and self._calculate_overlap(self._extract_keywords(text), longterm) >= 0.85:
            return

        section = LONGTERM_SECTION_BY_CATEGORY.get((category or "").strip().lower(), "重要事实")
        bullet = f"- {text.replace('\n', ' ')}"

        markdown = longterm
        if not markdown:
            markdown = self._render_config_template(LONGTERM_CONFIG_NAME)

        updated = self._append_bullet_to_longterm_section(markdown, section, bullet)
        self.save_config(LONGTERM_CONFIG_NAME, updated)

    @staticmethod
    def _extract_fields(text: str | None, labels: List[str]) -> dict:
        return {label: _extract_field_value(text, label) for label in labels}

    def _extract_profile_fields(self, labels: List[str]) -> dict:
        profile_text = self.load_config("PROFILE") or ""
        return self._extract_fields(profile_text, labels)

    @staticmethod
    def _merge_fields(primary: dict, fallback: dict) -> dict:
        merged = dict(primary)
        for key, value in fallback.items():
            if not merged.get(key) and value:
                merged[key] = value
        return merged

    @staticmethod
    def _normalize_onboarding_text(value: str | None, max_len: int = 120) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[:max_len]

    def get_onboarding_profile(self) -> dict:
        return self.get_user_profile(allow_fallback=False)

    def has_completed_first_contact(self) -> bool:
        profile = self.get_user_profile(allow_fallback=False)
        return all(profile.get(field) for field in USER_REQUIRED_FIELDS)

    def save_first_contact_profile(
        self,
        display_name: str | None = None,
        goal: str | None = None,
    ) -> dict:
        updates = {}
        if display_name:
            updates["称呼"] = self._normalize_onboarding_text(display_name, max_len=32)
        if goal:
            updates["长期目标"] = self._normalize_onboarding_text(goal, max_len=180)
        if updates:
            self.update_user_profile(updates)
        return self.get_user_profile(allow_fallback=False)

    def get_identity_profile(self, allow_fallback: bool = True) -> dict:
        identity_text = self.load_config("IDENTITY") or ""
        fields = self._extract_fields(identity_text, IDENTITY_FIELDS)
        if not allow_fallback:
            return fields
        fallback = self._extract_profile_fields(["名称", "角色", "风格"])
        return self._merge_fields(fields, fallback)

    def get_user_profile(self, allow_fallback: bool = True) -> dict:
        user_text = self.load_config("USER") or ""
        fields = self._extract_fields(user_text, USER_FIELDS)
        if not allow_fallback:
            return fields
        fallback = self._extract_profile_fields(USER_FIELDS)
        return self._merge_fields(fields, fallback)

    def get_soul_profile(self, allow_fallback: bool = True) -> dict:
        soul_text = self.load_config("SOUL") or ""
        fields = self._extract_fields(soul_text, SOUL_FIELDS)
        if not allow_fallback:
            return fields
        fallback = self._extract_profile_fields(SOUL_FIELDS)
        return self._merge_fields(fields, fallback)

    def update_user_profile(self, updates: dict) -> dict:
        if not updates:
            return self.get_user_profile(allow_fallback=False)

        content = self.load_config("USER") or self._render_config_template("USER")
        lines = content.splitlines()

        for label, raw_value in updates.items():
            if label not in USER_FIELDS:
                continue
            value = self._normalize_onboarding_text(raw_value, max_len=180)
            if not value:
                continue

            replaced = False
            pattern = re.compile(
                rf"^\s*[-*]?\s*(?:\*\*)?{re.escape(label)}[：:](?:\*\*)?\s*.*$"
            )
            for idx, line in enumerate(lines):
                if pattern.match(line.strip()):
                    prefix = "- " if line.lstrip().startswith("-") else ""
                    lines[idx] = f"{prefix}**{label}：** {value}".rstrip()
                    replaced = True
                    break

            if not replaced:
                lines.append(f"- **{label}：** {value}")

        updated = "\n".join(lines).rstrip() + "\n"
        self.save_config("USER", updated)
        return self.get_user_profile(allow_fallback=False)

    def list_memory_files(self) -> List[dict]:
        files: List[dict] = []
        longterm = self.get_config_path(LONGTERM_CONFIG_NAME)
        if longterm.exists():
            stat = longterm.stat()
            files.append(
                {
                    "name": LONGTERM_FILE_NAME,
                    "type": "longterm",
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                }
            )
        for item in sorted(self.memory_path.glob("*.md"), reverse=True):
            stat = item.stat()
            files.append(
                {
                    "name": item.name,
                    "type": "daily",
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                }
            )
        return files

    def load_memory_file(self, filename: str) -> Optional[str]:
        normalized_filename = (filename or "").strip()
        if normalized_filename in LEGACY_LONGTERM_FILE_NAMES:
            normalized_filename = LONGTERM_FILE_NAME
        path = self.get_config_path(LONGTERM_CONFIG_NAME) if normalized_filename == LONGTERM_FILE_NAME else self.memory_path / normalized_filename
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _is_daily_memory_filename(filename: str) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", filename or ""))

    def save_memory_file(self, filename: str, content: str) -> bool:
        normalized_filename = (filename or "").strip()
        if normalized_filename in LEGACY_LONGTERM_FILE_NAMES:
            normalized_filename = LONGTERM_FILE_NAME
        if normalized_filename == LONGTERM_FILE_NAME:
            self.save_config(LONGTERM_CONFIG_NAME, content)
            return True
        if not self._is_daily_memory_filename(normalized_filename):
            return False
        (self.memory_path / normalized_filename).write_text(content, encoding="utf-8")
        return True

    def reset_memory_file(self, filename: str) -> Optional[str]:
        normalized_filename = (filename or "").strip()
        if normalized_filename in LEGACY_LONGTERM_FILE_NAMES:
            normalized_filename = LONGTERM_FILE_NAME
        if normalized_filename == LONGTERM_FILE_NAME:
            content = self._render_config_template(LONGTERM_CONFIG_NAME)
            self.save_config(LONGTERM_CONFIG_NAME, content)
            return content

        if not self._is_daily_memory_filename(normalized_filename):
            return None

        date_str = normalized_filename.replace(".md", "")
        content = f"# {date_str}\n"
        (self.memory_path / normalized_filename).write_text(content, encoding="utf-8")
        return content

    def read_memory_lines(
        self,
        filename: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> Optional[str]:
        content = self.load_memory_file(filename)
        if content is None:
            return None
        lines = content.splitlines()
        if not lines:
            return ""

        start = max(1, start_line or 1) - 1
        end = end_line or len(lines)
        selected = lines[start:end]
        return "\n".join(f"{idx:4d} | {line}" for idx, line in enumerate(selected, start=start + 1))

    def search_memory_enhanced(self, keyword: str, context_lines: int = 3) -> List[dict]:
        results: List[dict] = []
        all_candidates: list[tuple[dict, float]] = []

        def add_file_candidates(source_name: str, content: str):
            if not content:
                return
            lines = content.splitlines()
            if not lines:
                return

            if BM25_AVAILABLE:
                tokenized_lines = [self._tokenize(line) for line in lines]
                bm25 = BM25Okapi(tokenized_lines)
                query_tokens = self._tokenize(keyword)
                scores = bm25.get_scores(query_tokens)
                for idx, score in enumerate(scores):
                    if score > 0.0:
                        all_candidates.append((
                            {"source": source_name, "line_idx": idx, "lines": lines},
                            score
                        ))
            else:
                matches = self._find_matches_with_context(content, keyword, context_lines)
                if matches:
                    results.append({"source": source_name, "matches": matches})

        longterm = self.load_config(LONGTERM_CONFIG_NAME)
        add_file_candidates(LONGTERM_FILE_NAME, longterm)

        for path in sorted(self.memory_path.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
                add_file_candidates(f"memory/{path.name}", content)
            except Exception:
                continue

        if BM25_AVAILABLE and all_candidates:
            all_candidates.sort(key=lambda x: x[1], reverse=True)
            merged_by_source: dict[str, dict] = {}
            seen_line_pairs: dict[str, set[tuple[int, int]]] = {}

            for candidate, score in all_candidates:
                source = candidate["source"]
                line_idx = candidate["line_idx"]
                lines = candidate["lines"]

                if source not in merged_by_source:
                    merged_by_source[source] = {"source": source, "matches": []}
                if source not in seen_line_pairs:
                    seen_line_pairs[source] = set()

                start = max(0, line_idx - context_lines)
                end = min(len(lines), line_idx + context_lines + 1)

                overlaps = False
                for (s, e) in seen_line_pairs[source]:
                    if not (end < s or start > e):
                        overlaps = True
                        break
                if overlaps:
                    continue

                seen_line_pairs[source].add((start, end))
                content = "\n".join(lines[start:end])
                merged_by_source[source]["matches"].append({
                    "start_line": start + 1,
                    "end_line": end,
                    "content": content
                })

            results.extend(merged_by_source.values())

        # Semantic search via embedding index (hybrid ranking)
        eidx = self._get_embedding_index()
        if eidx is not None:
            try:
                self._index_memory_for_semantic(eidx)
                semantic_hits = eidx.search(keyword, top_k=5)
                seen = {r["source"] for r in results}
                for hit in semantic_hits:
                    eid = hit["id"]
                    source, _, line_part = eid.partition("::L")
                    if source in seen:
                        continue
                    seen.add(source)
                    try:
                        line_idx = int(line_part) - 1
                    except ValueError:
                        line_idx = 0
                    content = self.load_memory_file(source.replace("memory/", ""))
                    if content:
                        lines_list = content.splitlines()
                        start = max(0, line_idx - context_lines)
                        end = min(len(lines_list), line_idx + context_lines + 1)
                        block = "\n".join(
                            f"{no+1:4d} | {lines_list[no]}" for no in range(start, end)
                        )
                        results.append({
                            "source": source,
                            "matches": [{
                                "start_line": start + 1,
                                "end_line": end,
                                "content": block,
                            }],
                        })
            except Exception:
                pass

        return results

    def _index_memory_for_semantic(self, eidx: "EmbeddingIndex") -> None:
        """Lazily index memory entries for semantic search (skips if unchanged)."""
        import hashlib
        entries: list[dict] = []
        sources = (
            [(self.get_config_path("MERMORY"), "MERMORY.md")]
            + [
                (p, f"memory/{p.name}")
                for p in sorted(self.memory_path.glob("*.md"))
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name)
            ]
        )
        hasher = hashlib.md5()
        for path, source_name in sources:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                hasher.update(content.encode())
                for idx, line in enumerate(content.splitlines()):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    entries.append({
                        "id": f"{source_name}::L{idx + 1}",
                        "text": stripped,
                    })
            except OSError:
                continue
        new_hash = hasher.hexdigest()
        if new_hash == self._memory_content_hash:
            return
        self._memory_content_hash = new_hash
        if entries:
            eidx._invalidate_cache()
            eidx.index_entries(entries)

    def _tokenize(self, text: str) -> list[str]:
        text = text.lower().strip()
        tokens = re.findall(r"[\w\u4e00-\u9fa5]+", text)
        return tokens or [text]

    def _find_matches_with_context(self, content: str, keyword: str, context_lines: int = 3) -> List[dict]:
        lines = content.split("\n")
        needle = keyword.lower().strip()
        if not needle:
            return []

        matched: Set[int] = set()
        for idx, line in enumerate(lines):
            if needle in line.lower():
                for j in range(max(0, idx - context_lines), min(len(lines), idx + context_lines + 1)):
                    matched.add(j)

        if not matched:
            return []

        sorted_lines = sorted(matched)
        merged: List[tuple[int, int]] = []
        start = end = sorted_lines[0]
        for index in sorted_lines[1:]:
            if index <= end + 1:
                end = index
            else:
                merged.append((start, end))
                start = end = index
        merged.append((start, end))

        payload: List[dict] = []
        for start_idx, end_idx in merged:
            block = "\n".join(f"{line_no + 1:4d} | {lines[line_no]}" for line_no in range(start_idx, end_idx + 1))
            payload.append({
                "start_line": start_idx + 1,
                "end_line": end_idx + 1,
                "content": block,
            })
        return payload

    def _extract_keywords(self, text: str) -> Set[str]:
        stopwords = {
            "the", "and", "for", "with", "that", "this", "you", "your", "are", "was", "were", "have", "has",
            "from", "will", "would", "could", "should", "about", "what", "when", "where", "which", "need",
            "want", "just", "like", "dont", "cant", "into", "then", "than", "some", "more", "less",
        }
        words = re.findall(r"[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,}", text.lower())
        return {word for word in words if word not in stopwords}

    def _calculate_overlap(self, keywords: Set[str], text: str) -> float:
        if not keywords:
            return 0.0
        haystack = text.lower()
        matched = sum(1 for item in keywords if item in haystack)
        return matched / len(keywords)

    def check_duplicate_memory(self, content: str, threshold: float = 0.7) -> bool:
        keywords = self._extract_keywords(content)
        if not keywords:
            return False

        today = self.get_daily_memory_path()
        if today.exists():
            daily_text = today.read_text(encoding="utf-8")
            if self._calculate_overlap(keywords, daily_text) >= threshold:
                return True

        longterm = self.load_config(LONGTERM_CONFIG_NAME)
        if longterm and self._calculate_overlap(keywords, longterm) >= threshold:
            return True

        for file in self.get_recent_memory_day(days=2):
            text = (self.memory_path / file).read_text(encoding="utf-8")
            if self._calculate_overlap(keywords, text) >= threshold:
                return True

        return False

    def get_user_timezone(self) -> str:
        profile = self.get_user_profile(allow_fallback=True)
        return str(profile.get("时区") or "").strip()

    def has_cross_day_repeat(
        self,
        content: str,
        threshold: float = 0.7,
        days: int = 7,
        today_date: datetime | None = None,
    ) -> bool:
        keywords = self._extract_keywords(content)
        if not keywords:
            return False

        today = today_date.date() if today_date else datetime.now().date()
        for path in self.memory_path.glob("*.md"):
            if not self._is_daily_memory_filename(path.name):
                continue
            try:
                file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date == today:
                continue
            if abs((today - file_date).days) > days:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if self._calculate_overlap(keywords, text) >= threshold:
                return True
        return False

    def get_recent_memory_day(self, days: int = 2) -> List[str]:
        names: List[str] = []
        for offset in range(days):
            day = datetime.now() - timedelta(days=offset)
            filename = f"{day.strftime('%Y-%m-%d')}.md"
            if (self.memory_path / filename).exists():
                names.append(filename)
        return names

    def cleanup_old_memories(self, days: int = 30) -> List[str]:
        deleted: List[str] = []
        cutoff = datetime.now() - timedelta(days=days)
        for path in self.memory_path.glob("*.md"):
            try:
                file_date = datetime.strptime(path.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink(missing_ok=True)
                deleted.append(path.name)
        return deleted

    def save_session_summary(self, filename: str, content: str) -> None:
        (self.memory_path / filename).write_text(content, encoding="utf-8")

    def list_session_summaries(self) -> List[dict]:
        summaries: List[dict] = []
        for path in sorted(self.memory_path.glob("*.md"), reverse=True):
            if re.match(r"\d{4}-\d{2}-\d{2}\.md$", path.name):
                continue
            match = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", path.name)
            date_value = match.group(1) if match else ""
            slug = match.group(2) if match else path.stem
            stat = path.stat()
            summaries.append(
                {
                    "filename": path.name,
                    "date": date_value,
                    "slug": slug,
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                }
            )
        return summaries

    def load_session_summary(self, filename: str) -> Optional[str]:
        path = self.memory_path / filename
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def session_file(self, session_id: str) -> Path:
        return self.sessions_path / f"{session_id}.json"

    def session_exists(self, session_id: str) -> bool:
        return self.session_file(session_id).exists()

    def load_session_data(self, session_id: str) -> dict:
        path = self.session_file(session_id)
        if not path.exists():
            return {
                "id": session_id,
                "created_at": datetime.now().timestamp(),
                "updated_at": datetime.now().timestamp(),
                "messages": [],
            }
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {
                "id": session_id,
                "created_at": datetime.now().timestamp(),
                "updated_at": datetime.now().timestamp(),
                "messages": [],
            }

    def save_session_data(self, session_id: str, data: dict) -> None:
        now = datetime.now().timestamp()
        data.setdefault("id", session_id)
        data.setdefault("created_at", now)
        data["updated_at"] = now
        self.session_file(session_id).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def delete_session(self, session_id: str) -> bool:
        path = self.session_file(session_id)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    def list_sessions(self) -> List[dict]:
        sessions: List[dict] = []
        for path in self.sessions_path.glob("*.json"):
            stat = path.stat()
            created_at = stat.st_ctime
            updated_at = stat.st_mtime
            description = ""

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    created_at = float(data.get("created_at") or created_at)
                    updated_at = float(data.get("updated_at") or updated_at)
                    description = str(data.get("description") or "")
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                pass

            sessions.append(
                {
                    "id": path.stem,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "description": description,
                }
            )
        return sorted(sessions, key=lambda item: item["created_at"], reverse=True)
