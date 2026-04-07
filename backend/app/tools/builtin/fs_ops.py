"""Workspace file tools guarded by local safety policy."""

from __future__ import annotations

from pathlib import Path

from .policy import LocalToolPolicy


class WorkspaceFileTool:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager

    def _default_output_dir(self) -> Path:
        preferred = self.workspace.workspace_path / "claw_file"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            return preferred
        except OSError:
            return self.workspace.workspace_path

    def _policy(self) -> LocalToolPolicy:
        return LocalToolPolicy.from_workspace(self.workspace)

    def list_dir(self, path: str = ".", recursive: bool = False, max_entries: int = 200) -> str:
        policy = self._policy()
        if not policy.enabled:
            return "文件工具已在配置中禁用。"

        target, error = policy.resolve_working_directory(path, self.workspace.workspace_path)
        if error:
            return error

        entries: list[str] = []
        if recursive:
            for item in sorted(target.rglob("*")):
                rel = item.relative_to(target)
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{rel.as_posix()}{suffix}")
                if len(entries) >= max_entries:
                    break
        else:
            for item in sorted(target.iterdir()):
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{suffix}")
                if len(entries) >= max_entries:
                    break

        header = f"Directory: {target}"
        if not entries:
            return header + "\n(empty)"

        if len(entries) >= max_entries:
            entries.append("... (truncated)")
        return header + "\n" + "\n".join(entries)

    def read_text(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        policy = self._policy()
        if not policy.enabled:
            return "文件工具已在配置中禁用。"

        raw_path = (path or "").strip()
        if not raw_path:
            return "请提供文件路径。"

        base_dir = self.workspace.workspace_path
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = base_dir / candidate

        try:
            resolved = candidate.resolve()
        except OSError:
            return "文件路径解析失败。"

        if not policy.is_path_allowed(resolved):
            return f"文件路径不在白名单内: {resolved}"
        if not resolved.exists() or not resolved.is_file():
            return f"文件不存在: {resolved}"

        start = max(1, int(start_line or 1))
        end = max(start, int(end_line or start))

        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return "当前仅支持读取 UTF-8 文本文件。"
        except OSError as exc:
            return f"读取失败: {exc}"

        if not lines:
            return f"{resolved}\n(file is empty)"

        start_idx = start - 1
        end_idx = min(end, len(lines))
        selected = lines[start_idx:end_idx]
        body = "\n".join(selected)
        header = f"{resolved} lines {start}-{end_idx}"
        text, clipped = policy.clip_text(header + "\n" + body)
        if clipped:
            text += "\n... (truncated by max_output_chars)"
        return text

    def write_text(self, path: str, content: str, mode: str = "overwrite") -> str:
        policy = self._policy()
        if not policy.enabled:
            return "文件工具已在配置中禁用。"

        raw_path = (path or "").strip()
        if not raw_path:
            return "请提供文件路径。"

        base_dir = self.workspace.workspace_path
        default_output_dir = self._default_output_dir()
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            # 仅文件名时，默认写到 workspace/claw_file；显式目录仍相对 workspace 解析。
            if candidate.parent == Path("."):
                candidate = default_output_dir / candidate.name
            else:
                candidate = base_dir / candidate

        try:
            resolved = candidate.resolve()
        except OSError:
            return "文件路径解析失败。"

        parent = resolved.parent
        if not policy.is_path_allowed(parent):
            return f"写入路径不在白名单内: {resolved}"

        write_mode = (mode or "overwrite").strip().lower()
        if write_mode not in {"overwrite", "append", "create"}:
            return "mode 仅支持 overwrite / append / create。"

        if write_mode == "create" and resolved.exists():
            return f"文件已存在，create 模式拒绝覆盖: {resolved}"

        try:
            parent.mkdir(parents=True, exist_ok=True)
            if write_mode == "append":
                with resolved.open("a", encoding="utf-8") as fh:
                    fh.write(content)
            else:
                resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败: {exc}"

        return f"写入成功: {resolved}"