"""Terminal rendering helpers using Rich."""

from __future__ import annotations


def tool_start(name: str, args: dict | None = None) -> str:
    if args:
        brief = str(args)
        if len(brief) > 60:
            brief = brief[:57] + "..."
        return f"  🔧 {name} ({brief})"
    return f"  🔧 {name}  ⠋ ..."


def tool_end(success: bool, summary: str = "", duration_ms: float = 0) -> str:
    icon = "✅" if success else "❌"
    dur = f" ({duration_ms / 1000:.1f}s)" if duration_ms > 0 else ""
    line = f"  {icon}{dur}"
    if summary:
        line += f"\n     └─ {summary[:200]}"
    return line


def tool_error(name: str, error: str) -> str:
    return f"  ❌ {name}: {error[:200]}"


def assistant_header(name: str = "CrabClaw") -> str:
    return f"\n🦀 {name}:"


def user_prompt() -> str:
    return "🦀 你: "
