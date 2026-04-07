"""Memory flush manager to trigger silent memory-saving rounds."""

from __future__ import annotations

from datetime import datetime


class MemoryFlushManager:
    def __init__(
        self,
        context_window: int = 128000,
        compression_threshold: float = 0.8,
        soft_threshold_tokens: int = 4000,
        enabled: bool = True,
    ):
        self.context_window = context_window
        self.compression_threshold = compression_threshold
        self.soft_threshold_tokens = soft_threshold_tokens
        self.enabled = enabled
        self._flush_triggered = False

    def should_trigger_flush(self, current_tokens: int) -> bool:
        if not self.enabled or self._flush_triggered:
            return False

        trigger_point = int(self.context_window * self.compression_threshold - self.soft_threshold_tokens)
        if current_tokens >= trigger_point:
            self._flush_triggered = True
            return True
        return False

    def get_flush_prompt(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            "压缩前记忆整理。\n"
            "当前上下文已接近压缩阈值，请先保存重要用户信息。\n"
            f"今天：{today}\n"
            "请使用 memory_add 保存每日事实，使用 memory_update_longterm 保存可长期沿用的信息。\n"
            "如果没有需要保存的内容，请严格回复：[SILENT]"
        )

    @staticmethod
    def is_silent_response(response: str) -> bool:
        return response.strip() == "[SILENT]"

    def reset(self) -> None:
        self._flush_triggered = False

    def get_status(self) -> dict:
        trigger_point = int(self.context_window * self.compression_threshold - self.soft_threshold_tokens)
        return {
            "enabled": self.enabled,
            "context_window": self.context_window,
            "compression_threshold": self.compression_threshold,
            "soft_threshold_tokens": self.soft_threshold_tokens,
            "trigger_point": trigger_point,
            "flush_triggered": self._flush_triggered,
        }
