"""Local safety policy for workspace tools."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ...workspace.hub import WorkspaceManager


def _to_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_cmd_name(token: str) -> str:
    if not token:
        return ""
    token = token.strip().strip('"').strip("'")
    base = Path(token).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base


def _strip_wrapping_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


@dataclass
class LocalToolPolicy:
    enabled: bool
    allowed_dirs: list[Path]
    allowed_commands: set[str]
    blocked_terms: list[str]
    default_timeout_seconds: int
    max_timeout_seconds: int
    max_output_chars: int

    @classmethod
    def from_workspace(cls, workspace: WorkspaceManager) -> "LocalToolPolicy":
        raw_config = workspace.load_global_config()
        runtime_cfg = raw_config.get("execution", {}) if isinstance(raw_config, dict) else {}

        default_allowed_dirs = [
            workspace.workspace_path,
            workspace.workspace_path.parent,
            workspace.workspace_path.parent.parent / "outputs",
        ]

        configured_dirs = runtime_cfg.get("allowed_dirs") if isinstance(runtime_cfg, dict) else None
        if isinstance(configured_dirs, list) and configured_dirs:
            allowed_dirs = [Path(str(item)).expanduser() for item in configured_dirs]
        else:
            allowed_dirs = default_allowed_dirs

        env_allowed_dirs = os.getenv("CRABCLAW_ALLOWED_DIRS", "")
        if env_allowed_dirs.strip():
            allowed_dirs = [Path(item.strip()).expanduser() for item in env_allowed_dirs.split(",") if item.strip()]

        resolved_dirs: list[Path] = []
        for item in allowed_dirs:
            try:
                resolved_dirs.append(item.resolve())
            except OSError:
                continue

        default_commands = {
            "python",
            "pip",
            "node",
            "npm",
            "npx",
            "git",
            "soffice",
            "pdftoppm",
        }
        configured_commands = runtime_cfg.get("allowed_commands") if isinstance(runtime_cfg, dict) else None
        if isinstance(configured_commands, list) and configured_commands:
            allowed_commands = {_normalize_cmd_name(str(item)) for item in configured_commands if str(item).strip()}
        else:
            allowed_commands = default_commands

        env_allowed_cmds = os.getenv("CRABCLAW_ALLOWED_COMMANDS", "")
        if env_allowed_cmds.strip():
            allowed_commands = {
                _normalize_cmd_name(item)
                for item in env_allowed_cmds.split(",")
                if item.strip()
            }

        default_blocked_terms = [
            "shutdown",
            "diskpart",
            "format ",
            "reg delete",
            "rd /s /q",
            "del /f /s /q",
            "remove-item -recurse",
            "remove-item -force",
            "rm -rf /",
        ]
        configured_blocked = runtime_cfg.get("blocked_terms") if isinstance(runtime_cfg, dict) else None
        if isinstance(configured_blocked, list) and configured_blocked:
            blocked_terms = [str(item).strip().lower() for item in configured_blocked if str(item).strip()]
        else:
            blocked_terms = default_blocked_terms

        enabled = _to_bool(runtime_cfg.get("enabled") if isinstance(runtime_cfg, dict) else None, True)
        enabled = _to_bool(os.getenv("CRABCLAW_EXECUTION_ENABLED", enabled), enabled)

        default_timeout_seconds = _to_int(
            runtime_cfg.get("default_timeout_seconds") if isinstance(runtime_cfg, dict) else None,
            90,
        )
        max_timeout_seconds = _to_int(
            runtime_cfg.get("max_timeout_seconds") if isinstance(runtime_cfg, dict) else None,
            240,
        )
        max_output_chars = _to_int(
            runtime_cfg.get("max_output_chars") if isinstance(runtime_cfg, dict) else None,
            12000,
        )

        max_timeout_seconds = max(10, max_timeout_seconds)
        default_timeout_seconds = min(max(5, default_timeout_seconds), max_timeout_seconds)
        max_output_chars = max(1000, max_output_chars)

        return cls(
            enabled=enabled,
            allowed_dirs=resolved_dirs,
            allowed_commands=allowed_commands,
            blocked_terms=blocked_terms,
            default_timeout_seconds=default_timeout_seconds,
            max_timeout_seconds=max_timeout_seconds,
            max_output_chars=max_output_chars,
        )

    def is_path_allowed(self, path: Path) -> bool:
        if not self.allowed_dirs:
            return False
        try:
            resolved = path.resolve()
        except OSError:
            return False

        for base in self.allowed_dirs:
            if resolved == base or base in resolved.parents:
                return True
        return False

    def resolve_working_directory(self, raw_path: str | None, fallback_dir: Path) -> tuple[Path | None, str | None]:
        base = fallback_dir
        candidate = Path(raw_path).expanduser() if raw_path and raw_path.strip() else base

        if not candidate.is_absolute():
            candidate = base / candidate

        try:
            resolved = candidate.resolve()
        except OSError:
            return None, "工作目录解析失败。"

        if not resolved.exists() or not resolved.is_dir():
            return None, f"工作目录不存在: {resolved}"

        if not self.is_path_allowed(resolved):
            return None, f"工作目录不在白名单内: {resolved}"

        return resolved, None

    def validate_command(self, command: str) -> tuple[bool, str | None, list[str]]:
        raw = (command or "").strip()
        if not raw:
            return False, "命令不能为空。", []

        lowered = raw.lower()
        for term in self.blocked_terms:
            if term and term in lowered:
                return False, f"命令包含高风险片段，已拦截: {term}", []

        try:
            tokens = shlex.split(raw, posix=False)
        except ValueError as exc:
            return False, f"命令解析失败: {exc}", []

        if not tokens:
            return False, "命令不能为空。", []

        # shlex(posix=False) 在 Windows 下会保留外围引号，这会让 pip/python 收到错误参数。
        tokens = [_strip_wrapping_quotes(token) for token in tokens]

        unsupported_tokens = {"|", "||", "&&", ">", ">>", "<", "1>", "2>", "&"}
        if any(token in unsupported_tokens for token in tokens):
            return False, "当前执行器不支持管道或重定向，请拆分为单条命令执行。", []

        command_name = _normalize_cmd_name(tokens[0])
        if command_name not in self.allowed_commands:
            allowed = ", ".join(sorted(self.allowed_commands))
            return False, f"命令未在白名单中: {command_name or tokens[0]}；允许命令: {allowed}", []

        return True, None, tokens

    def clip_text(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_output_chars:
            return text, False
        clipped = text[: self.max_output_chars]
        return clipped, True

    @staticmethod
    def format_allowed_dirs(dirs: Iterable[Path]) -> str:
        return ", ".join(str(item) for item in dirs)