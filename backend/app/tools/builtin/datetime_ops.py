"""Date/time query tool for the CrabClaw agent."""

from __future__ import annotations

from datetime import datetime


class DateTimeTool:
    def run(self, query: str = "") -> str:
        from datetime import timezone
        now = datetime.now()
        utc_now = datetime.now(timezone.utc)
        lines = [
            f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.astimezone().tzinfo or 'local'})",
            f"UTC 时间:  {utc_now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"星期:      {self._weekday_cn(now.weekday())}",
            f"ISO 周数:  {now.isocalendar()[1]}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _weekday_cn(weekday: int) -> str:
        return ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][weekday]
