"""Local skills registry backed by workspace/skills directory."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx

from ..workspace.hub import WorkspaceManager


class SkillRegistry:
    def __init__(self, workspace: WorkspaceManager):
        self.workspace = workspace
        self.workspace.skills_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_skill_id(value: str) -> str:
        raw = (value or "").strip().lower()
        slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
        return slug[:64] if slug else "skill"

    @staticmethod
    def _split_frontmatter(markdown: str) -> tuple[Dict[str, str], str]:
        text = markdown or ""
        if not text.startswith("---"):
            return {}, text

        normalized = text.replace("\r\n", "\n")
        lines = normalized.split("\n")
        if not lines or lines[0].strip() != "---":
            return {}, text

        end_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break

        if end_idx < 0:
            return {}, text

        frontmatter: Dict[str, str] = {}
        for line in lines[1:end_idx]:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            frontmatter[key.strip().lower()] = val.strip().strip('"').strip("'")

        body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
        return frontmatter, body

    @staticmethod
    def _extract_title(markdown_body: str) -> str:
        for line in (markdown_body or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    @staticmethod
    def _extract_description(markdown_body: str) -> str:
        for line in (markdown_body or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            return stripped
        return ""

    def _skill_markdown_path(self, skill_dir: Path) -> Optional[Path]:
        preferred = skill_dir / "SKILL.md"
        if preferred.exists():
            return preferred

        for candidate in skill_dir.glob("*.md"):
            if candidate.name.lower() == "skill.md":
                return candidate
        return None

    def _load_from_dir(self, skill_dir: Path, include_prompt: bool = False) -> Optional[dict]:
        md_path = self._skill_markdown_path(skill_dir)
        if md_path is None:
            return None

        try:
            raw_markdown = md_path.read_text(encoding="utf-8")
        except OSError:
            return None

        frontmatter, body = self._split_frontmatter(raw_markdown)
        parsed_name = frontmatter.get("name") or self._extract_title(body) or skill_dir.name
        parsed_desc = frontmatter.get("description") or self._extract_description(body)
        skill_id = self._sanitize_skill_id(skill_dir.name)

        item = {
            "id": skill_id,
            "name": parsed_name,
            "description": parsed_desc,
            "path": str(skill_dir),
            "entry": str(md_path),
            "updated_at": md_path.stat().st_mtime,
        }

        if include_prompt:
            item["prompt"] = body.strip()

        return item

    def list_skills(self) -> List[dict]:
        skills: List[dict] = []
        if not self.workspace.skills_path.exists():
            return skills

        for item in sorted(self.workspace.skills_path.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_dir():
                continue
            loaded = self._load_from_dir(item)
            if loaded:
                skills.append(loaded)
        return skills

    def get_skill(self, skill_id: str, include_prompt: bool = False) -> Optional[dict]:
        normalized = self._sanitize_skill_id(skill_id)
        target_dir = self.workspace.skills_path / normalized
        if not target_dir.exists() or not target_dir.is_dir():
            return None
        return self._load_from_dir(target_dir, include_prompt=include_prompt)

    def delete_skill(self, skill_id: str) -> bool:
        normalized = self._sanitize_skill_id(skill_id)
        target_dir = self.workspace.skills_path / normalized
        if not target_dir.exists() or not target_dir.is_dir():
            return False
        shutil.rmtree(target_dir, ignore_errors=True)
        return True

    def _install_skill_dir(self, source_dir: Path) -> Optional[dict]:
        source = source_dir.resolve()
        loaded = self._load_from_dir(source)
        if loaded is None:
            return None

        requested_id = loaded.get("name") or source.name
        target_id = self._sanitize_skill_id(requested_id)
        target_dir = self.workspace.skills_path / target_id

        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

        shutil.copytree(source, target_dir)
        return self.get_skill(target_id)

    def install_from_local(self, source_path: str) -> List[dict]:
        source = Path((source_path or "").strip()).expanduser()
        if not source.exists():
            raise FileNotFoundError("Source path does not exist")

        installed: List[dict] = []
        candidates: List[Path] = []

        if source.is_file() and source.name.lower() == "skill.md":
            with tempfile.TemporaryDirectory(prefix="crabclaw-skill-") as tmp:
                temp_dir = Path(tmp) / self._sanitize_skill_id(source.parent.name or "skill")
                temp_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, temp_dir / "SKILL.md")
                result = self._install_skill_dir(temp_dir)
                if result:
                    installed.append(result)
            return installed

        if source.is_dir() and (source / "SKILL.md").exists():
            candidates = [source]
        elif source.is_dir():
            for md_path in source.rglob("SKILL.md"):
                candidates.append(md_path.parent)
        else:
            raise ValueError("Only folders or SKILL.md files are supported")

        dedup: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in dedup:
                continue
            dedup.add(resolved)
            result = self._install_skill_dir(resolved)
            if result:
                installed.append(result)

        return installed

    def install_from_url(self, url: str) -> List[dict]:
        target_url = (url or "").strip()
        if not target_url:
            raise ValueError("URL is required")

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(target_url)
            response.raise_for_status()

            content_type = (response.headers.get("content-type") or "").lower()
            is_zip = target_url.lower().endswith(".zip") or "application/zip" in content_type

            if is_zip:
                with tempfile.TemporaryDirectory(prefix="crabclaw-skill-zip-") as tmp:
                    zip_path = Path(tmp) / "skill.zip"
                    zip_path.write_bytes(response.content)
                    extract_dir = Path(tmp) / "unzipped"
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        with zipfile.ZipFile(zip_path, "r") as zf:
                            zf.extractall(extract_dir)
                    except zipfile.BadZipFile as exc:
                        raise ValueError("Downloaded ZIP is invalid or corrupted") from exc
                    return self.install_from_local(str(extract_dir))

            text = response.text
            if "<html" in text.lower() and "</html>" in text.lower():
                raise ValueError("URL appears to be an HTML page, please use a direct raw SKILL.md or ZIP URL")

            frontmatter, body = self._split_frontmatter(text)
            parsed = urlparse(target_url)
            basename = Path(parsed.path).stem or "skill"
            target_id = self._sanitize_skill_id(frontmatter.get("name") or basename)
            target_dir = self.workspace.skills_path / target_id

            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.mkdir(parents=True, exist_ok=True)

            (target_dir / "SKILL.md").write_text(text, encoding="utf-8")
            if not body.strip():
                raise ValueError("Downloaded content does not look like a valid skill markdown")

            item = self.get_skill(target_id)
            return [item] if item else []
