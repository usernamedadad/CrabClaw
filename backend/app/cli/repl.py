"""Interactive REPL for the CrabClaw CLI."""

from __future__ import annotations

import sys

from ..agent.core_agent import CrabClawAgent
from .render import user_prompt
from .stream import consume_stream


async def run_repl(agent: CrabClawAgent) -> None:
    """Run interactive read-eval-print loop."""
    print("🦀 CrabClaw CLI — 输入消息开始对话，输入 /quit 退出")
    print()

    session_id: str | None = None

    while True:
        try:
            user_input = input(user_prompt())
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        text = user_input.strip()
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            print("👋 再见！")
            break

        new_sid, _ = await consume_stream(
            agent.astream_chat(text, session_id),
            track_session=True,
        )
        if new_sid:
            session_id = new_sid
        print()
