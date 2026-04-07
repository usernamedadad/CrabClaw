"""Execute shell commands inside local sandbox boundaries."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .policy import LocalToolPolicy


class ExecuteCommandTool:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager

    def _default_working_directory(self) -> Path:
        preferred = self.workspace.workspace_path / "claw_file"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            return preferred
        except OSError:
            return self.workspace.workspace_path

    def _policy(self) -> LocalToolPolicy:
        return LocalToolPolicy.from_workspace(self.workspace)

    def _append_audit(self, record: dict) -> None:
        log_path = self.workspace.root_path / "execution_audit.log"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return

    def run(self, command: str, working_directory: str = "", timeout_seconds: int | None = None) -> str:
        policy = self._policy()
        if not policy.enabled:
            return "命令执行工具已在配置中禁用。"

        ok, error, tokens = policy.validate_command(command)
        if not ok:
            return error or "命令校验失败。"

        default_cwd = self._default_working_directory()

        if not (working_directory or "").strip():
            # 若命令参数里引用了仅在 workspace 根可见的相对路径，则回退到 workspace 根执行。
            for token in tokens[1:]:
                if token.startswith("-"):
                    continue
                rel = Path(token)
                if rel.is_absolute():
                    continue
                root_target = self.workspace.workspace_path / rel
                default_target = default_cwd / rel
                if root_target.exists() and not default_target.exists():
                    default_cwd = self.workspace.workspace_path
                    break

        working_dir, dir_error = policy.resolve_working_directory(working_directory, default_cwd)
        if dir_error:
            return dir_error

        requested_timeout = timeout_seconds if timeout_seconds is not None else policy.default_timeout_seconds
        safe_timeout = min(max(5, int(requested_timeout)), policy.max_timeout_seconds)

        started = datetime.utcnow()
        try:
            proc = subprocess.run(
                tokens,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                timeout=safe_timeout,
                shell=False,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined = (
                f"command: {command}\n"
                f"cwd: {working_dir}\n"
                f"exit_code: {proc.returncode}\n"
                "--- stdout ---\n"
                f"{stdout}\n"
                "--- stderr ---\n"
                f"{stderr}"
            )
            output, clipped = policy.clip_text(combined)
            if clipped:
                output += "\n... (truncated by max_output_chars)"

            self._append_audit(
                {
                    "time": started.isoformat() + "Z",
                    "command": command,
                    "cwd": str(working_dir),
                    "exit_code": proc.returncode,
                    "timeout_seconds": safe_timeout,
                    "status": "ok",
                }
            )
            return output
        except subprocess.TimeoutExpired:
            self._append_audit(
                {
                    "time": started.isoformat() + "Z",
                    "command": command,
                    "cwd": str(working_dir),
                    "timeout_seconds": safe_timeout,
                    "status": "timeout",
                }
            )
            return f"命令超时（>{safe_timeout}s），已终止。"
        except Exception as exc:  # noqa: BLE001
            self._append_audit(
                {
                    "time": started.isoformat() + "Z",
                    "command": command,
                    "cwd": str(working_dir),
                    "timeout_seconds": safe_timeout,
                    "status": "error",
                    "error": str(exc),
                }
            )
            return f"命令执行失败: {exc}"